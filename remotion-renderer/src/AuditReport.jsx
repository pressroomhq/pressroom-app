/**
 * AuditReport — data-driven version of Ralph's DreamFactoryReport.
 * Accepts { data } prop containing audit + branding + scenes.
 * Used for personalized outreach videos — shows real SEO findings for target company.
 */
import React from 'react';
import {
  AbsoluteFill,
  Sequence,
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  spring,
} from 'remotion';

const FPS = 30;
const s = (sec) => Math.round(sec * FPS);

function fadeIn(frame, start = 0, dur = 20) {
  return interpolate(frame, [start, start + dur], [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });
}

// ── Opening card ──────────────────────────────────────────────────────────────

function OpeningCard({ scenes, branding }) {
  const frame = useCurrentFrame();
  const opacity = fadeIn(frame, 0, 20);
  const accent = branding.primary_color || '#ffb000';

  return (
    <AbsoluteFill style={{
      backgroundColor: '#0a0a0a',
      justifyContent: 'center',
      alignItems: 'center',
      fontFamily: `'IBM Plex Mono', monospace`,
    }}>
      {branding.logo_url && (
        <img
          src={branding.logo_url}
          alt="logo"
          style={{ height: 80, marginBottom: 36, opacity, objectFit: 'contain' }}
        />
      )}
      <div style={{ color: '#fff', fontSize: 44, fontWeight: 700, opacity, textAlign: 'center', maxWidth: 900 }}>
        {scenes.opening.text}
      </div>
      <div style={{ color: accent, fontSize: 24, marginTop: 16, opacity, letterSpacing: 3 }}>
        {scenes.opening.subtext}
      </div>
    </AbsoluteFill>
  );
}

// ── SEO Score ─────────────────────────────────────────────────────────────────

function SEOScore({ scenes, branding }) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const score = scenes.seo_score.score;
  const scoreColor = score >= 70 ? '#33ff33' : score >= 45 ? '#ffb000' : '#ff4444';
  const animatedScore = Math.round(
    interpolate(frame, [0, fps * 1.5], [0, score], { extrapolateRight: 'clamp' })
  );
  const textOpacity = fadeIn(frame, fps * 1.5, 15);

  return (
    <AbsoluteFill style={{
      backgroundColor: '#0a0a0a',
      justifyContent: 'center',
      alignItems: 'center',
      fontFamily: `'IBM Plex Mono', monospace`,
    }}>
      <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: 14, letterSpacing: 6, marginBottom: 24 }}>
        DIGITAL PRESENCE SCORE
      </div>
      <div style={{ color: scoreColor, fontSize: 160, fontWeight: 700, lineHeight: 1 }}>
        {animatedScore}
      </div>
      <div style={{ color: scoreColor, fontSize: 18, letterSpacing: 2, marginTop: 8 }}>/ 100</div>
      <div style={{ color: 'rgba(255,255,255,0.6)', fontSize: 20, marginTop: 32, opacity: textOpacity, textAlign: 'center', maxWidth: 700 }}>
        {scenes.seo_score.caption}
      </div>
    </AbsoluteFill>
  );
}

// ── Issues breakdown (animated bar chart) ────────────────────────────────────

function IssuesBreakdown({ scenes, branding }) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const bars = scenes.issues_breakdown.bars || [];
  const maxCount = Math.max(...bars.map(b => b.count), 1);

  return (
    <AbsoluteFill style={{
      backgroundColor: '#0a0a0a',
      padding: '80px 120px',
      fontFamily: `'IBM Plex Mono', monospace`,
    }}>
      <div style={{
        color: 'rgba(255,255,255,0.4)',
        fontSize: 13,
        letterSpacing: 6,
        marginBottom: 16,
        opacity: fadeIn(frame),
      }}>
        {scenes.issues_breakdown.title || 'WHAT WE FOUND'}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 28, marginTop: 40 }}>
        {bars.map((bar, i) => {
          const delay = i * 10;
          const pct = interpolate(frame, [delay, delay + fps * 0.8], [0, bar.count / maxCount], {
            extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
          });
          return (
            <div key={i} style={{ opacity: fadeIn(frame, delay, 15) }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                <span style={{ color: '#fff', fontSize: 18, letterSpacing: 2 }}>{bar.category}</span>
                <span style={{ color: bar.color, fontSize: 18, fontWeight: 700 }}>{bar.count}</span>
              </div>
              <div style={{ background: 'rgba(255,255,255,0.08)', height: 12, width: '100%' }}>
                <div style={{
                  background: bar.color,
                  height: '100%',
                  width: `${pct * 100}%`,
                  transition: 'width 0.1s',
                }} />
              </div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
}

// ── Missing channel callout ───────────────────────────────────────────────────

function MissingChannel({ channel_data, branding }) {
  const frame = useCurrentFrame();
  const accent = branding.primary_color || '#ffb000';
  const opacity = fadeIn(frame, 0, 20);
  const y = interpolate(frame, [0, 20], [40, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });

  return (
    <AbsoluteFill style={{
      backgroundColor: '#0a0a0a',
      justifyContent: 'center',
      alignItems: 'center',
      fontFamily: `'IBM Plex Mono', monospace`,
    }}>
      <div style={{ opacity, transform: `translateY(${y}px)`, textAlign: 'center' }}>
        <div style={{
          color: accent,
          fontSize: 64,
          fontWeight: 700,
          letterSpacing: 4,
          marginBottom: 24,
        }}>
          {channel_data.channel}
        </div>
        <div style={{
          background: '#ff4444',
          color: '#fff',
          display: 'inline-block',
          padding: '8px 24px',
          fontSize: 16,
          letterSpacing: 4,
          marginBottom: 32,
        }}>
          {channel_data.text}
        </div>
        <div style={{ color: 'rgba(255,255,255,0.5)', fontSize: 20, maxWidth: 700 }}>
          {channel_data.subtext}
        </div>
      </div>
    </AbsoluteFill>
  );
}

// ── GEO Readiness (progress bars) ────────────────────────────────────────────

function GEOReadiness({ scenes, branding }) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const accent = branding.primary_color || '#ffb000';
  const factors = scenes.geo_readiness.factors || [];

  return (
    <AbsoluteFill style={{
      backgroundColor: '#0a0a0a',
      padding: '80px 120px',
      fontFamily: `'IBM Plex Mono', monospace`,
    }}>
      <div style={{
        color: 'rgba(255,255,255,0.4)',
        fontSize: 13,
        letterSpacing: 6,
        marginBottom: 40,
        opacity: fadeIn(frame),
      }}>
        {scenes.geo_readiness.title || 'AI CITABILITY BREAKDOWN'}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
        {factors.map((f, i) => {
          const delay = i * 8;
          const pct = interpolate(frame, [delay, delay + fps * 0.8], [0, f.score / (f.max || 100)], {
            extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
          });
          const scoreColor = f.score >= 60 ? '#33ff33' : f.score >= 35 ? '#ffb000' : '#ff4444';
          return (
            <div key={i} style={{ opacity: fadeIn(frame, delay, 15) }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                <span style={{ color: '#fff', fontSize: 16, letterSpacing: 1 }}>{f.name}</span>
                <span style={{ color: scoreColor, fontSize: 16, fontWeight: 700 }}>{f.score}</span>
              </div>
              <div style={{ background: 'rgba(255,255,255,0.08)', height: 8, width: '100%' }}>
                <div style={{
                  background: scoreColor,
                  height: '100%',
                  width: `${pct * 100}%`,
                }} />
              </div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
}

// ── Top Fixes ─────────────────────────────────────────────────────────────────

function TopFixes({ scenes, branding }) {
  const frame = useCurrentFrame();
  const accent = branding.primary_color || '#ffb000';
  const fixes = scenes.top_fixes.fixes || [];
  const priorityColors = { P0: '#ff4444', P1: '#ffb000', P2: '#33ff33' };

  return (
    <AbsoluteFill style={{
      backgroundColor: '#0a0a0a',
      padding: '80px 120px',
      fontFamily: `'IBM Plex Mono', monospace`,
    }}>
      <div style={{
        color: 'rgba(255,255,255,0.4)',
        fontSize: 13,
        letterSpacing: 6,
        marginBottom: 40,
        opacity: fadeIn(frame),
      }}>
        TOP FIXES
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
        {fixes.map((fix, i) => {
          const delay = i * 15;
          return (
            <div key={i} style={{
              opacity: fadeIn(frame, delay, 15),
              transform: `translateY(${interpolate(frame, [delay, delay + 15], [20, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' })}px)`,
              display: 'flex',
              gap: 24,
              alignItems: 'flex-start',
            }}>
              <div style={{
                background: priorityColors[fix.priority] || '#888',
                color: '#000',
                fontSize: 12,
                fontWeight: 700,
                padding: '4px 10px',
                letterSpacing: 2,
                flexShrink: 0,
                marginTop: 4,
              }}>
                {fix.priority}
              </div>
              <div>
                <div style={{ color: '#fff', fontSize: 22, fontWeight: 700, marginBottom: 8 }}>{fix.title}</div>
                <div style={{ color: 'rgba(255,255,255,0.5)', fontSize: 16, lineHeight: 1.5 }}>{fix.detail}</div>
              </div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
}

// ── Credits ───────────────────────────────────────────────────────────────────

function AuditCredits({ scenes, branding }) {
  const frame = useCurrentFrame();
  const accent = branding.primary_color || '#ffb000';
  const opacity = fadeIn(frame, 0, 20);

  return (
    <AbsoluteFill style={{
      backgroundColor: accent,
      justifyContent: 'center',
      alignItems: 'center',
      fontFamily: `'IBM Plex Mono', monospace`,
    }}>
      <div style={{ opacity, textAlign: 'center' }}>
        <div style={{ color: '#000', fontSize: 32, fontWeight: 700, marginBottom: 16 }}>
          {scenes.credits.text}
        </div>
        <div style={{ color: 'rgba(0,0,0,0.6)', fontSize: 18, letterSpacing: 3, marginBottom: 8 }}>
          {scenes.credits.url}
        </div>
        <div style={{ color: 'rgba(0,0,0,0.5)', fontSize: 15 }}>
          {scenes.credits.tagline}
        </div>
      </div>
    </AbsoluteFill>
  );
}

// ── Main export ───────────────────────────────────────────────────────────────

export default function AuditReport({ data }) {
  if (!data) return null;

  const branding = data.branding || {};
  const scenes = data.scenes || {};

  let offset = 0;
  const seqs = [];

  const add = (durationSecs, Component, props = {}) => {
    const frames = s(durationSecs);
    seqs.push(
      <Sequence key={offset} from={offset} durationInFrames={frames}>
        <Component {...props} branding={branding} scenes={scenes} />
      </Sequence>
    );
    offset += frames;
  };

  add(scenes.opening?.duration_seconds || 4, OpeningCard);
  add(scenes.seo_score?.duration_seconds || 6, SEOScore);
  add(scenes.issues_breakdown?.duration_seconds || 7, IssuesBreakdown);

  for (const ch of (scenes.missing_channels || [])) {
    const frames = s(ch.duration_seconds || 3);
    seqs.push(
      <Sequence key={offset} from={offset} durationInFrames={frames}>
        <MissingChannel channel_data={ch} branding={branding} />
      </Sequence>
    );
    offset += frames;
  }

  add(scenes.geo_readiness?.duration_seconds || 6, GEOReadiness);
  add(scenes.top_fixes?.duration_seconds || 8, TopFixes);
  add(scenes.credits?.duration_seconds || 4, AuditCredits);

  return (
    <AbsoluteFill style={{ backgroundColor: '#0a0a0a' }}>
      {seqs}
    </AbsoluteFill>
  );
}
