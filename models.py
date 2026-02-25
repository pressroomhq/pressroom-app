import datetime
import uuid
from sqlalchemy import Column, Integer, String, Text, DateTime, Float, Boolean, ForeignKey, Enum as SAEnum, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import relationship
import enum

from database import Base


class SignalType(str, enum.Enum):
    github_release = "github_release"
    github_commit = "github_commit"
    hackernews = "hackernews"
    reddit = "reddit"
    rss = "rss"
    trend = "trend"
    web_search = "web_search"
    support = "support"
    performance = "performance"
    google_news = "google_news"
    devto = "devto"
    producthunt = "producthunt"


class ContentChannel(str, enum.Enum):
    linkedin = "linkedin"
    x_thread = "x_thread"
    facebook = "facebook"
    blog = "blog"
    devto = "devto"
    github_gist = "github_gist"
    release_email = "release_email"
    newsletter = "newsletter"
    yt_script = "yt_script"


class ContentStatus(str, enum.Enum):
    generating = "generating"
    queued = "queued"
    approved = "approved"
    spiked = "spiked"
    published = "published"


class StoryStatus(str, enum.Enum):
    draft = "draft"
    generating = "generating"
    complete = "complete"


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    domain = Column(String(500), default="", unique=True)
    is_demo = Column(Boolean, default=False, server_default="false")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    signals = relationship("Signal", back_populates="org", cascade="all, delete-orphan")
    briefs = relationship("Brief", back_populates="org", cascade="all, delete-orphan")
    contents = relationship("Content", back_populates="org", cascade="all, delete-orphan")
    settings = relationship("Setting", back_populates="org", cascade="all, delete-orphan")
    data_sources = relationship("DataSource", back_populates="org", cascade="all, delete-orphan")
    assets = relationship("CompanyAsset", back_populates="org", cascade="all, delete-orphan")
    stories = relationship("Story", back_populates="org", cascade="all, delete-orphan")
    audits = relationship("AuditResult", back_populates="org", cascade="all, delete-orphan")
    team_members = relationship("TeamMember", back_populates="org", cascade="all, delete-orphan")
    blog_posts = relationship("BlogPost", back_populates="org", cascade="all, delete-orphan")
    email_drafts = relationship("EmailDraft", back_populates="org", cascade="all, delete-orphan")
    seo_pr_runs = relationship("SeoPrRun", back_populates="org", cascade="all, delete-orphan")
    site_properties = relationship("SiteProperty", back_populates="org", cascade="all, delete-orphan")


class Signal(Base):
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    type = Column(SAEnum(SignalType, native_enum=False), nullable=False)
    source = Column(String(255), nullable=False)
    title = Column(String(500), nullable=False)
    body = Column(Text, default="")
    url = Column(String(1000), default="")
    raw_data = Column(Text, default="")
    prioritized = Column(Boolean, default=False)  # editor-prioritized for content gen
    times_used = Column(Integer, default=0)  # how many content pieces used this signal
    times_spiked = Column(Integer, default=0)  # how many times content from this signal was spiked
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    org = relationship("Organization", back_populates="signals")
    contents = relationship("Content", back_populates="signal")


class Brief(Base):
    __tablename__ = "briefs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    date = Column(String(10), nullable=False)
    summary = Column(Text, nullable=False)
    angle = Column(String(500), default="")
    signal_ids = Column(Text, default="")  # comma-separated
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    org = relationship("Organization", back_populates="briefs")
    contents = relationship("Content", back_populates="brief")


class Content(Base):
    __tablename__ = "content"

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    signal_id = Column(Integer, ForeignKey("signals.id"), nullable=True)
    brief_id = Column(Integer, ForeignKey("briefs.id"), nullable=True)
    story_id = Column(Integer, ForeignKey("stories.id"), nullable=True)
    channel = Column(SAEnum(ContentChannel, native_enum=False), nullable=False)
    status = Column(SAEnum(ContentStatus, native_enum=False), default=ContentStatus.queued)
    headline = Column(String(500), default="")
    body = Column(Text, nullable=False)
    body_raw = Column(Text, default="")  # pre-humanizer
    author = Column(String(100), default="company")
    source_signal_ids = Column(Text, default="")  # comma-separated signal IDs that fed this content
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    approved_at = Column(DateTime, nullable=True)
    published_at = Column(DateTime, nullable=True)
    scheduled_at = Column(DateTime, nullable=True)  # when to auto-publish (None = immediate on approve)
    post_id = Column(String(500), default="")       # platform post ID (e.g. LinkedIn URN, Dev.to article ID)
    post_url = Column(String(1000), default="")     # public URL of published post

    org = relationship("Organization", back_populates="contents")
    signal = relationship("Signal", back_populates="contents")
    brief = relationship("Brief", back_populates="contents")
    story = relationship("Story", back_populates="contents")
    performance = relationship("ContentPerformance", back_populates="content", cascade="all, delete-orphan")


class ContentPerformance(Base):
    """Point-in-time performance snapshot for published content."""
    __tablename__ = "content_performance"

    id = Column(Integer, primary_key=True, autoincrement=True)
    content_id = Column(Integer, ForeignKey("content.id"), nullable=False)
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    likes = Column(Integer, default=0)
    comments = Column(Integer, default=0)
    shares = Column(Integer, default=0)
    fetched_at = Column(DateTime, default=datetime.datetime.utcnow)

    content = relationship("Content", back_populates="performance")


class DataSource(Base):
    """External data connection — DreamFactory instance, database, API, etc."""
    __tablename__ = "data_sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    name = Column(String(255), nullable=False)         # e.g. "Intercom Data"
    description = Column(Text, default="")              # what this source contains
    category = Column(String(100), default="database")  # database, crm, analytics, support, custom
    connection_type = Column(String(50), default="mcp")  # mcp, rest_api
    base_url = Column(String(1000), default="")         # e.g. http://df.example.com
    api_key = Column(String(500), default="")           # auth key
    config = Column(Text, default="{}")                 # extra JSON config
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    org = relationship("Organization", back_populates="data_sources")


class CompanyAsset(Base):
    """Discovered or manually added company digital asset."""
    __tablename__ = "company_assets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    asset_type = Column(String(50), nullable=False)  # subdomain, blog, docs, repo, social, api_endpoint
    url = Column(String(1000), nullable=False)
    label = Column(String(255), default="")           # user-editable: "primary blog", "main docs"
    description = Column(String(1000), default="")
    discovered_via = Column(String(50), default="manual")  # onboarding, manual
    auto_discovered = Column(Boolean, default=False)
    metadata_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    org = relationship("Organization", back_populates="assets")


class Story(Base):
    """Editorial story — curated signals + angle for targeted content generation."""
    __tablename__ = "stories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    title = Column(String(500), nullable=False)
    angle = Column(Text, default="")
    editorial_notes = Column(Text, default="")
    status = Column(SAEnum(StoryStatus, native_enum=False), default=StoryStatus.draft)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    org = relationship("Organization", back_populates="stories")
    story_signals = relationship("StorySignal", back_populates="story", cascade="all, delete-orphan")
    contents = relationship("Content", back_populates="story")


class StorySignal(Base):
    """Join table — links signals to stories with per-signal editorial notes."""
    __tablename__ = "story_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    story_id = Column(Integer, ForeignKey("stories.id"), nullable=False)
    signal_id = Column(Integer, ForeignKey("signals.id"), nullable=True)
    wire_signal_id = Column(Integer, ForeignKey("wire_signals.id"), nullable=True)
    editor_notes = Column(Text, default="")
    sort_order = Column(Integer, default=0)

    story = relationship("Story", back_populates="story_signals")
    signal = relationship("Signal")
    wire_signal = relationship("WireSignal")


class ApiToken(Base):
    """Bearer token for API authentication — scoped to an org."""
    __tablename__ = "api_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    token = Column(String(500), nullable=False, unique=True, index=True)
    label = Column(String(255), default="")
    revoked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)

    org = relationship("Organization")


class ApiKey(Base):
    """Labeled Anthropic API key — account-level, assigned to orgs for usage tracking."""
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    label = Column(String(255), nullable=False)
    key_value = Column(String(500), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class AuditResult(Base):
    """Persisted audit result — SEO or README."""
    __tablename__ = "audit_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    audit_type = Column(String(50), nullable=False)  # seo, readme
    target = Column(String(1000), nullable=False)     # domain URL or owner/repo
    score = Column(Integer, default=0)
    total_issues = Column(Integer, default=0)
    result_json = Column(Text, default="{}")           # full audit result
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    org = relationship("Organization", back_populates="audits")
    action_items = relationship("AuditActionItem", back_populates="audit_result", cascade="all, delete-orphan")


class AuditActionItem(Base):
    """A single actionable finding from an audit — persisted, trackable."""
    __tablename__ = "audit_action_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    audit_result_id = Column(Integer, ForeignKey("audit_results.id"), nullable=True)
    priority = Column(String(50), default="medium")   # critical, high, medium, low
    category = Column(String(100), default="")        # technical, content, geo, robots, schema, performance
    title = Column(String(500), nullable=False)
    status = Column(String(50), default="open")       # open, in_progress, resolved
    evidence_json = Column(Text, default="{}")         # raw data: {url, found_value, expected, context}
    fix_instructions = Column(Text, default="")
    score_impact = Column(Integer, default=0)          # estimated score improvement if fixed
    first_seen = Column(DateTime, default=datetime.datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)

    org = relationship("Organization")
    audit_result = relationship("AuditResult", back_populates="action_items")


class TeamMember(Base):
    """Discovered or manually added team member."""
    __tablename__ = "team_members"

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    name = Column(String(255), nullable=False)
    title = Column(String(255), default="")
    bio = Column(Text, default="")
    photo_url = Column(String(1000), default="")
    linkedin_url = Column(String(1000), default="")
    github_username = Column(String(255), default="")       # matched from GitHub org scan
    github_access_token = Column(Text, default="")          # personal OAuth token for posting gists as this member
    linkedin_access_token = Column(Text, default="")    # personal OAuth token for posting as this member
    linkedin_author_urn = Column(String(255), default="")  # urn:li:person:XXXXX
    linkedin_token_expires_at = Column(Integer, default=0)  # unix timestamp
    email = Column(String(255), default="")
    expertise_tags = Column(Text, default="[]")  # JSON array of strings
    voice_style = Column(Text, default="")        # analyzed writing style description
    linkedin_post_samples = Column(Text, default="")  # pasted post samples for voice analysis
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    org = relationship("Organization", back_populates="team_members")


class BlogPost(Base):
    """Scraped blog post — context for the content engine."""
    __tablename__ = "blog_posts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    url = Column(String(1000), nullable=False)
    title = Column(String(500), default="")
    excerpt = Column(Text, default="")
    published_at = Column(DateTime, nullable=True)
    scraped_at = Column(DateTime, default=datetime.datetime.utcnow)

    org = relationship("Organization", back_populates="blog_posts")


class SeoPrRun(Base):
    """SEO PR pipeline run — tracks audit-to-PR lifecycle."""
    __tablename__ = "seo_pr_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    domain = Column(String(500), nullable=False)
    repo_url = Column(String(1000), default="")
    status = Column(String(50), default="pending")  # pending, auditing, analyzing, implementing, pushing, verifying, healing, complete, failed
    audit_id = Column(Integer, nullable=True)  # reference to audit_results
    plan_json = Column(Text, default="{}")  # the tiered plan
    pr_url = Column(String(1000), default="")
    branch_name = Column(String(255), default="")
    error = Column(Text, default="")
    changes_made = Column(Integer, default=0)
    deploy_status = Column(String(50), default="")  # pending, success, failed, healed
    deploy_log = Column(Text, default="")  # build log excerpt on failure
    heal_attempts = Column(Integer, default=0)  # how many fix attempts
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    org = relationship("Organization", back_populates="seo_pr_runs")


class SiteProperty(Base):
    """Bonded site + repo — links a domain to its source repo for SEO workflows."""
    __tablename__ = "site_properties"

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    name = Column(String(255), nullable=False)           # "DreamFactory Docs"
    domain = Column(String(500), nullable=False)          # "docs.dreamfactory.com"
    repo_url = Column(String(1000), default="")           # "https://github.com/owner/repo" (optional)
    base_branch = Column(String(100), default="main")
    site_type = Column(String(50), default="static")      # static, cms, app
    last_audit_score = Column(Integer, nullable=True)
    last_audit_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    org = relationship("Organization", back_populates="site_properties")


class ActivityLog(Base):
    """Persistent activity log — war room teletype history."""
    __tablename__ = "activity_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    level = Column(String(20), default="info")  # info, success, error, warn
    message = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

    org = relationship("Organization")


class Setting(Base):
    __tablename__ = "settings"
    __table_args__ = (UniqueConstraint("org_id", "key", name="uq_setting_org_key"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    key = Column(String(100), nullable=False, index=True)
    value = Column(Text, default="")
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    org = relationship("Organization", back_populates="settings")


class EmailDraft(Base):
    """Email draft — composed from release_email or newsletter content."""
    __tablename__ = "email_drafts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    content_id = Column(Integer, ForeignKey("content.id"), nullable=True)
    subject = Column(String(500), nullable=False)
    html_body = Column(Text, nullable=False)
    text_body = Column(Text, default="")
    from_name = Column(String(255), default="")
    status = Column(String(50), default="draft")  # draft, ready, sent
    recipients = Column(Text, default="[]")  # JSON array of email addresses
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    org = relationship("Organization", back_populates="email_drafts")
    content = relationship("Content")


class YouTubeScript(Base):
    """YouTube script — generated from content, exported as Remotion package."""
    __tablename__ = "youtube_scripts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    content_id = Column(Integer, ForeignKey("content.id"), nullable=True)
    title = Column(String(500))
    hook = Column(Text, default="")
    sections = Column(Text, default="[]")
    cta = Column(Text, default="")
    lower_thirds = Column(Text, default="[]")
    metadata_title = Column(String(100), default="")
    metadata_description = Column(Text, default="")
    metadata_tags = Column(Text, default="[]")
    remotion_package = Column(Text, default="{}")
    status = Column(String(50), default="draft")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class TokenUsage(Base):
    """Per-call Claude API token usage — tracks cost per org per operation."""
    __tablename__ = "token_usage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    operation = Column(String(100), nullable=False)
    model = Column(String(100), default="")
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    org = relationship("Organization")


class AIVisibilityQuestion(Base):
    """AI visibility questions — what customers ask LLMs about this space."""
    __tablename__ = "ai_visibility_questions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    question = Column(Text, nullable=False)
    position = Column(Integer, default=1)

    org = relationship("Organization")


class AIVisibilityResult(Base):
    """AI visibility results — raw LLM responses with citation scoring."""
    __tablename__ = "ai_visibility_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    question = Column(Text, nullable=False)
    provider = Column(String(50), nullable=False)
    response = Column(Text, default="")
    score = Column(String(20), default="absent")
    excerpt = Column(Text, default="")
    scanned_at = Column(DateTime, default=datetime.datetime.utcnow)

    org = relationship("Organization")


class CompetitorAudit(Base):
    """Competitive intelligence — audit results for competitor domains."""
    __tablename__ = "competitor_audits"

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    competitor_url = Column(String(1000), nullable=False)
    competitor_name = Column(String(255), default="")
    score = Column(Integer, default=0)
    ai_citability = Column(Integer, default=0)
    result_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


# ── Supabase Auth ──────────────────────────────────────────────────────────────

class Profile(Base):
    """Supabase Auth profile — linked to auth.users via UUID."""
    __tablename__ = "profiles"

    id = Column(PGUUID(as_uuid=True), primary_key=True)
    email = Column(String(255), nullable=False)
    name = Column(String(255), default="")
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Per-user social OAuth tokens (account-level, not org-level)
    linkedin_access_token = Column(Text, default="")
    linkedin_author_urn = Column(String(255), default="")
    linkedin_profile_name = Column(String(255), default="")
    linkedin_token_expires_at = Column(Integer, default=0)

    orgs = relationship("UserOrg", back_populates="profile")


class UserOrg(Base):
    """Many-to-many: profile ↔ org access."""
    __tablename__ = "user_orgs"
    __table_args__ = (UniqueConstraint("user_id", "org_id", name="uq_user_org"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(PGUUID(as_uuid=True), ForeignKey("profiles.id"), nullable=False)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    profile = relationship("Profile", back_populates="orgs")
    org = relationship("Organization")


# ── Legacy User Auth (DEPRECATED) ─────────────────────────────────────────────

# DEPRECATED — kept for reference, not used with Supabase Auth
class User(Base):
    """Login user — owns orgs, has a password, receives invite links."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    password_hash = Column(String(500), default="")  # empty until invite accepted
    name = Column(String(255), default="")
    is_admin = Column(Boolean, default=False)
    is_active = Column(Boolean, default=False)  # False until invite accepted
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_login_at = Column(DateTime, nullable=True)

    # Relationships removed — UserOrg now references profiles.id, not users.id


# DEPRECATED — kept for reference, not used with Supabase Auth
class UserSession(Base):
    """Browser session token — issued on login, stored in localStorage."""
    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token = Column(String(500), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User")


class AccessRequest(Base):
    """Public request-for-access form submission."""
    __tablename__ = "access_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), nullable=False)
    name = Column(String(255), default="")
    reason = Column(Text, default="")
    status = Column(String(50), default="pending")  # pending, approved, rejected
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    reviewed_at = Column(DateTime, nullable=True)


# DEPRECATED — kept for reference, not used with Supabase Auth
class InviteToken(Base):
    """One-time invite link — sent to new users to set their password."""
    __tablename__ = "invite_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    token = Column(String(500), nullable=False, unique=True, index=True)
    email = Column(String(255), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


# ── User Feedback ────────────────────────────────────────────────────────────

class Feedback(Base):
    """User feedback submissions."""
    __tablename__ = "feedback"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(PGUUID(as_uuid=True), ForeignKey("profiles.id"), nullable=True)
    email = Column(String(255), nullable=False)
    category = Column(String(100), nullable=False)  # feature_request, bug, incorrect_scan, general, other
    message = Column(Text, nullable=False)
    page = Column(String(255), default="")  # which view/page they were on
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    status = Column(String(50), default="new")  # new, reviewed, resolved
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


# ── SCOUT / SIGINT PIPELINE ──────────────────────────────────────────────────

class Source(Base):
    """Global source library — shared across all orgs.

    A source is a crawlable feed: a subreddit, HN keyword, RSS URL, X search,
    or trend query. Crawled once per sweep, results land in raw_signals.
    Orgs subscribe to sources via OrgSource.
    """
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(String(50), nullable=False)       # reddit | hackernews | rss | x_search | trends | web_search
    name = Column(String(255), nullable=False)       # human label: "r/devops", "HN: api management"
    config = Column(Text, default="{}")             # JSON: {subreddit: "devops"} or {keyword: "API"} or {url: "..."}
    category_tags = Column(Text, default="[]")      # JSON: ["devops","api","enterprise"] — for recommendations
    active = Column(Boolean, default=True)
    fetch_interval_hours = Column(Integer, default=24)
    last_fetched_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    org_sources = relationship("OrgSource", back_populates="source", cascade="all, delete-orphan")


class OrgSource(Base):
    """Per-org source subscription — which orgs monitor which global sources."""
    __tablename__ = "org_sources"
    __table_args__ = (UniqueConstraint("org_id", "source_id", name="uq_org_source"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False)
    enabled = Column(Boolean, default=True)           # user can toggle off without deleting
    added_at = Column(DateTime, default=datetime.datetime.utcnow)

    org = relationship("Organization")
    source = relationship("Source", back_populates="org_sources")


class RawSignal(Base):
    """Raw signal from a sweep — unfiltered, not org-specific.

    Crawled once, shared. Per-org relevance is computed at query time by
    scoring this signal's embedding against the org's fingerprint.
    Deduplication is cosine similarity against recent raw signals (>0.92 = skip).
    """
    __tablename__ = "raw_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=True)
    type = Column(String(50), nullable=False)        # mirrors source type
    source_name = Column(String(255), default="")    # denormalized label for display
    title = Column(String(500), nullable=False)
    body = Column(Text, default="")
    url = Column(String(1000), default="", unique=True)
    raw_data = Column(Text, default="{}")            # original fetch payload (JSON)
    embedding = Column(Text, default="")             # JSON float array from voyage-3-lite
    embedding_model = Column(String(50), default="") # e.g. "voyage-3-lite"
    fetched_at = Column(DateTime, default=datetime.datetime.utcnow)

    source = relationship("Source")


class OrgFingerprint(Base):
    """Per-org embedding fingerprint — encodes topics, industry, competitors.

    Rebuilt whenever org settings change. Used to score raw signals for
    relevance via cosine similarity.
    """
    __tablename__ = "org_fingerprints"

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, unique=True)
    fingerprint_text = Column(Text, default="")      # the text that was embedded
    embedding = Column(Text, default="")             # JSON float array
    embedding_model = Column(String(50), default="")
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)

    org = relationship("Organization")


# ── WIRE (COMPANY PULSE) ─────────────────────────────────────────────────────

class WireSource(Base):
    """Company-owned feed — GitHub repo, blog RSS, changelog, docs.

    Always relevant to the org — no scoring needed. Separate from Scout/SIGINT.
    These are the company's own channels, not industry intelligence.
    """
    __tablename__ = "wire_sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    type = Column(String(50), nullable=False)        # github_repo | github_org | blog_rss | changelog | docs_rss
    name = Column(String(255), nullable=False)        # "dreamfactory/dreamfactory", "DreamFactory Blog"
    config = Column(Text, default="{}")              # JSON: {repo: "owner/repo", token: "..."} etc.
    active = Column(Boolean, default=True)
    last_fetched_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    org = relationship("Organization")
    pulses = relationship("WireSignal", back_populates="wire_source", cascade="all, delete-orphan")


class WireSignal(Base):
    """Signal from a company's own Wire — always org-specific, always relevant.

    GitHub releases, commits, blog posts, changelog entries. No relevance
    scoring. Fed directly into content gen alongside scored SIGINT signals.
    """
    __tablename__ = "wire_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    wire_source_id = Column(Integer, ForeignKey("wire_sources.id"), nullable=True)
    type = Column(String(50), nullable=False)         # github_release | github_commit | blog_post | changelog
    source_name = Column(String(255), default="")
    title = Column(String(500), nullable=False)
    body = Column(Text, default="")
    url = Column(String(1000), default="")
    raw_data = Column(Text, default="{}")
    prioritized = Column(Boolean, default=False)
    times_used = Column(Integer, default=0)
    times_spiked = Column(Integer, default=0)
    fetched_at = Column(DateTime, default=datetime.datetime.utcnow)

    org = relationship("Organization")
    wire_source = relationship("WireSource", back_populates="pulses")
