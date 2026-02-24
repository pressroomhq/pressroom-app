import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Float, ForeignKey, Enum as SAEnum, UniqueConstraint
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


class ContentChannel(str, enum.Enum):
    linkedin = "linkedin"
    x_thread = "x_thread"
    facebook = "facebook"
    blog = "blog"
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
    domain = Column(String(500), default="")
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
    type = Column(SAEnum(SignalType), nullable=False)
    source = Column(String(255), nullable=False)
    title = Column(String(500), nullable=False)
    body = Column(Text, default="")
    url = Column(String(1000), default="")
    raw_data = Column(Text, default="")
    prioritized = Column(Integer, default=0)  # 1 = editor-prioritized for content gen
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
    channel = Column(SAEnum(ContentChannel), nullable=False)
    status = Column(SAEnum(ContentStatus), default=ContentStatus.queued)
    headline = Column(String(500), default="")
    body = Column(Text, nullable=False)
    body_raw = Column(Text, default="")  # pre-humanizer
    author = Column(String(100), default="company")
    source_signal_ids = Column(Text, default="")  # comma-separated signal IDs that fed this content
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    approved_at = Column(DateTime, nullable=True)
    published_at = Column(DateTime, nullable=True)
    scheduled_at = Column(DateTime, nullable=True)  # when to auto-publish (None = immediate on approve)

    org = relationship("Organization", back_populates="contents")
    signal = relationship("Signal", back_populates="contents")
    brief = relationship("Brief", back_populates="contents")
    story = relationship("Story", back_populates="contents")


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
    auto_discovered = Column(Integer, default=0)
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
    status = Column(SAEnum(StoryStatus), default=StoryStatus.draft)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    org = relationship("Organization", back_populates="stories")
    story_signals = relationship("StorySignal", back_populates="story", cascade="all, delete-orphan")
    contents = relationship("Content", back_populates="story")


class StorySignal(Base):
    """Join table — links signals to stories with per-signal editorial notes."""
    __tablename__ = "story_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    story_id = Column(Integer, ForeignKey("stories.id"), nullable=False)
    signal_id = Column(Integer, ForeignKey("signals.id"), nullable=False)
    editor_notes = Column(Text, default="")
    sort_order = Column(Integer, default=0)

    story = relationship("Story", back_populates="story_signals")
    signal = relationship("Signal")


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
    email = Column(String(255), default="")
    expertise_tags = Column(Text, default="[]")  # JSON array of strings
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

    org = relationship("Organization")
