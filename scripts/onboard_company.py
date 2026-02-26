#!/usr/bin/env python3
"""
Pressroom company onboarding script.

Runs the full pipeline that the HTTP onboarding flow does:
  1. Crawl domain (discover pages + social profiles)
  2. Synthesize company profile with Claude
  3. Generate scout sources (subreddits, HN keywords, RSS, GitHub repos)
  4. Create organization record
  5. Save all settings (voice profile, scout sources, metadata)
  6. Create company_assets (homepage, blog, docs, social profiles, repos)
  7. Run initial SEO audit + save results + action items
  8. Build org fingerprint (for SIGINT signal scoring)

Usage:
    cd pressroom-app
    source venv/bin/activate
    python scripts/onboard_company.py sendspark.com
    python scripts/onboard_company.py sendspark.com integrate.io baremetrics.com

Options:
    --audit-only   Skip crawl/profile, just run SEO audit for existing orgs
    --dry-run      Print what would be done without writing to DB
"""

import asyncio
import json
import sys
import os
import argparse
import logging

# Path setup
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

logging.basicConfig(level=logging.WARNING)
log = logging.getLogger("onboard")

from database import async_session
from services.data_layer import DataLayer
from services.onboarding import (
    crawl_domain, synthesize_profile, generate_scout_sources, profile_to_settings
)
from services.seo_audit import audit_domain

# Asset type mapping from crawl page labels → company_asset types
_ASSET_TYPE_MAP = {
    "blog": "blog", "news": "blog", "articles": "blog",
    "docs": "docs", "documentation": "docs", "api": "docs", "reference": "docs",
    "product": "product", "features": "product", "platform": "product",
    "sub:blog": "blog", "sub:news": "blog", "sub:docs": "docs",
    "sub:developers": "docs", "sub:api": "docs",
}


def _page_label_to_asset_type(label: str) -> str:
    if label.startswith("sub:"):
        sub = label.removeprefix("sub:")
        return _ASSET_TYPE_MAP.get(label, _ASSET_TYPE_MAP.get(sub, "subdomain"))
    return _ASSET_TYPE_MAP.get(label, "page")


async def onboard_one(domain: str, dry_run: bool = False) -> dict:
    """Full onboarding pipeline for a single domain."""
    print(f"\n{'='*60}")
    print(f"  Onboarding: {domain}")
    print(f"{'='*60}")

    async with async_session() as session:
        dl = DataLayer(session, org_id=None)

        # ── 1. Check for existing org ──
        from models import Organization
        from sqlalchemy import select
        existing = (await session.execute(
            select(Organization).where(Organization.domain == domain)
        )).scalar_one_or_none()

        if existing:
            print(f"  [!] Org already exists: {existing.name} (id={existing.id})")
            print(f"      Use --audit-only to re-run the audit for this org.")
            return {"skipped": True, "org_id": existing.id, "domain": domain}

        # ── 2. Crawl domain ──
        print(f"  [1/5] Crawling {domain}...")
        crawl_data = await crawl_domain(domain)
        pages_found = crawl_data.get("pages_found", [])
        socials = crawl_data.get("social_profiles", {})
        print(f"        Pages found: {pages_found}")
        print(f"        Socials found: {list(socials.keys())}")

        if not crawl_data.get("pages"):
            print(f"  [!] No pages crawled — check that {domain} is reachable")
            return {"error": "crawl_failed", "domain": domain}

        # ── 3. Synthesize profile ──
        print(f"  [2/5] Synthesizing profile...")
        from config import settings as app_settings
        api_key = app_settings.anthropic_api_key
        profile = await synthesize_profile(crawl_data, api_key=api_key)
        if profile.get("error"):
            print(f"  [!] Profile synthesis failed: {profile['error']}")
            return {"error": "profile_failed", "domain": domain}

        company_name = profile.get("company_name") or domain.split(".")[0].title()
        print(f"        Company: {company_name}")
        print(f"        Industry: {profile.get('industry', 'unknown')}")

        # ── 4. Generate scout sources ──
        print(f"  [3/5] Generating scout sources...")
        scout_sources = await generate_scout_sources(profile, api_key=api_key)
        print(f"        Subreddits: {scout_sources.get('subreddits', [])[:3]}...")

        if dry_run:
            print(f"\n  [DRY RUN] Would create org '{company_name}' with {len(pages_found)} assets")
            return {"dry_run": True, "domain": domain, "company_name": company_name}

        # ── 5. Create org ──
        print(f"  [4/5] Creating org + saving settings...")
        org = await dl.create_org(name=company_name, domain=domain)
        org_id = org["id"]
        dl.org_id = org_id
        print(f"        Org created: id={org_id}")

        # Grant the operator access — mirror what the HTTP onboard flow does.
        # Operator = whoever owns the first org in the system.
        from sqlalchemy import text as sa_text
        owner = (await session.execute(
            sa_text("SELECT user_id FROM user_orgs WHERE org_id = (SELECT MIN(id) FROM organizations) LIMIT 1")
        )).scalar_one_or_none()
        if owner:
            await session.execute(sa_text(
                "INSERT INTO user_orgs (user_id, org_id) VALUES (:uid, :oid) ON CONFLICT DO NOTHING"
            ), {"uid": owner, "oid": org_id})
            await session.flush()

        # Voice settings from profile
        settings_map = profile_to_settings(profile)

        # Company metadata
        settings_map["onboard_company_name"] = company_name
        settings_map["onboard_domain"] = domain
        if profile.get("industry"):
            settings_map["onboard_industry"] = profile["industry"]
        if profile.get("topics"):
            settings_map["onboard_topics"] = json.dumps(profile["topics"])
        if profile.get("competitors"):
            settings_map["onboard_competitors"] = json.dumps(profile["competitors"])
        if profile.get("social_profiles"):
            settings_map["social_profiles"] = json.dumps(profile["social_profiles"])
        settings_map["onboard_complete"] = "true"

        # Scout sources
        if scout_sources.get("subreddits"):
            settings_map["scout_subreddits"] = json.dumps(scout_sources["subreddits"])
        if scout_sources.get("hn_keywords"):
            settings_map["scout_hn_keywords"] = json.dumps(scout_sources["hn_keywords"])
        if scout_sources.get("rss_feeds"):
            settings_map["scout_rss_feeds"] = json.dumps(scout_sources["rss_feeds"])
        if scout_sources.get("web_queries"):
            settings_map["scout_web_queries"] = json.dumps(scout_sources["web_queries"])
        if scout_sources.get("github_repos"):
            settings_map["scout_github_repos"] = json.dumps(scout_sources["github_repos"])

        for key, value in settings_map.items():
            await dl.set_setting(key, value)

        await session.flush()
        print(f"        Settings saved: {len(settings_map)} keys")

        # ── 6. Create company assets ──
        asset_count = 0

        # Homepage
        homepage_url = crawl_data.get("domain", f"https://{domain}")
        await dl.save_asset({
            "asset_type": "page", "url": homepage_url,
            "label": "homepage", "description": f"Main website",
            "discovered_via": "onboarding", "auto_discovered": True,
        })
        asset_count += 1

        # Crawled pages
        for label, page_data in crawl_data.get("pages", {}).items():
            if label == "homepage":
                continue
            url = page_data.get("url", "") if isinstance(page_data, dict) else str(page_data)
            if not url:
                continue
            asset_type = _page_label_to_asset_type(label)
            await dl.save_asset({
                "asset_type": asset_type, "url": url,
                "label": label.removeprefix("sub:"),
                "description": "", "discovered_via": "onboarding", "auto_discovered": True,
            })
            asset_count += 1

        # Social profiles (from crawl + from Claude synthesis)
        all_socials = {**socials, **(profile.get("social_profiles") or {})}
        for platform, url in all_socials.items():
            if url:
                await dl.save_asset({
                    "asset_type": "social", "url": url, "label": platform,
                    "description": f"{platform} profile",
                    "discovered_via": "onboarding", "auto_discovered": True,
                })
                asset_count += 1

        # GitHub repos from scout sources
        for repo in (scout_sources.get("github_repos") or []):
            repo_name = repo if isinstance(repo, str) else repo.get("full_name", "")
            if repo_name:
                await dl.save_asset({
                    "asset_type": "repo",
                    "url": f"https://github.com/{repo_name}" if "/" in repo_name else repo_name,
                    "label": repo_name.split("/")[-1] if "/" in repo_name else repo_name,
                    "description": "", "discovered_via": "onboarding", "auto_discovered": True,
                })
                asset_count += 1

        await session.flush()
        print(f"        Assets created: {asset_count}")

        await dl.commit()
        print(f"        Committed.")

    # ── 7. SEO audit (new session — org now exists) ──
    print(f"  [5/5] Running SEO audit...")
    async with async_session() as session:
        dl = DataLayer(session, org_id=org_id)
        api_key = app_settings.anthropic_api_key
        result = await audit_domain(domain, max_pages=10, api_key=api_key)

        if "error" in result:
            print(f"  [!] SEO audit failed: {result['error']}")
        else:
            saved = await dl.save_audit({
                "audit_type": "seo",
                "target": result.get("domain", domain),
                "score": result.get("recommendations", {}).get("score", 0),
                "total_issues": result.get("recommendations", {}).get("total_issues", 0),
                "result": result,
            })
            action_items = result.get("action_items", [])
            if action_items:
                await dl.upsert_action_items(saved["id"], action_items)
            await dl.commit()
            score = result.get("recommendations", {}).get("score", 0)
            print(f"        Audit saved: id={saved['id']}, score={score}/100, action_items={len(action_items)}")

    # ── 8. Build org fingerprint ──
    print(f"  [+] Building org fingerprint...")
    try:
        from services.sweep import rebuild_org_fingerprint
        async with async_session() as session:
            dl = DataLayer(session, org_id=org_id)
            ok = await rebuild_org_fingerprint(org_id)
            print(f"        Fingerprint: {'ok' if ok else 'failed (no Voyage key?)'}")
    except Exception as e:
        print(f"        Fingerprint skipped: {e}")

    print(f"\n  Done: {company_name} (org_id={org_id})")
    return {"org_id": org_id, "domain": domain, "company_name": company_name, "assets": asset_count}


async def audit_only(domain: str) -> None:
    """Re-run SEO audit for an existing org by domain."""
    from models import Organization
    from sqlalchemy import select
    from config import settings as app_settings

    async with async_session() as session:
        existing = (await session.execute(
            select(Organization).where(Organization.domain == domain)
        )).scalar_one_or_none()

        if not existing:
            print(f"  [!] No org found for domain '{domain}'")
            return

        org_id = existing.id
        print(f"  Re-auditing {domain} (org_id={org_id})...")
        dl = DataLayer(session, org_id=org_id)
        api_key = app_settings.anthropic_api_key

        result = await audit_domain(domain, max_pages=10, api_key=api_key)
        if "error" in result:
            print(f"  [!] Audit failed: {result['error']}")
            return

        saved = await dl.save_audit({
            "audit_type": "seo",
            "target": result.get("domain", domain),
            "score": result.get("recommendations", {}).get("score", 0),
            "total_issues": result.get("recommendations", {}).get("total_issues", 0),
            "result": result,
        })
        action_items = result.get("action_items", [])
        if action_items:
            await dl.upsert_action_items(saved["id"], action_items)
        await dl.commit()
        score = result.get("recommendations", {}).get("score", 0)
        print(f"  Done: audit_id={saved['id']}, score={score}/100, items={len(action_items)}")


async def main():
    parser = argparse.ArgumentParser(description="Onboard companies into Pressroom")
    parser.add_argument("domains", nargs="+", help="Domain(s) to onboard, e.g. sendspark.com")
    parser.add_argument("--audit-only", action="store_true", help="Re-run SEO audit for existing orgs")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done, no DB writes")
    args = parser.parse_args()

    results = []
    for domain in args.domains:
        domain = domain.strip().lower().removeprefix("https://").removeprefix("http://").rstrip("/")
        try:
            if args.audit_only:
                await audit_only(domain)
            else:
                result = await onboard_one(domain, dry_run=args.dry_run)
                results.append(result)
        except Exception as e:
            print(f"\n[ERROR] {domain}: {e}")
            import traceback
            traceback.print_exc()
            results.append({"error": str(e), "domain": domain})

    if results and not args.audit_only:
        print(f"\n{'='*60}")
        print("  Summary")
        print(f"{'='*60}")
        for r in results:
            if r.get("skipped"):
                print(f"  SKIPPED  {r['domain']} (org_id={r['org_id']} already exists)")
            elif r.get("dry_run"):
                print(f"  DRY RUN  {r['domain']} → {r.get('company_name')}")
            elif r.get("error"):
                print(f"  ERROR    {r['domain']}: {r['error']}")
            else:
                print(f"  OK       {r['domain']} → {r.get('company_name')} (org_id={r['org_id']}, assets={r.get('assets')})")


if __name__ == "__main__":
    asyncio.run(main())
