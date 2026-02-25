import React from 'react';
import {
  AbsoluteFill,
  Sequence,
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  spring,
  OffthreadVideo,
  staticFile,
} from 'remotion';

const FPS = 30;
const s = (seconds) => Math.round(seconds * FPS);

// ── Helpers ───────────────────────────────────────────────────────────────────

function fadeIn(frame, startFrame = 0, duration = 20) {
  return interpolate(frame, [startFrame, startFrame + duration], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
}

function slideUp(frame, startFrame = 0, duration = 20) {
  return interpolate(frame, [startFrame, startFrame + duration], [30, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
}

// ── Scene: Hook card ──────────────────────────────────────────────────────────

function HookCard({ hook, title, branding }) {
  const frame = useCurrentFrame();
  const opacity = fadeIn(frame);
  const y = slideUp(frame);
  const accentColor = branding.primary_color || '#ffb000';

  return (
    <AbsoluteFill style={{
      backgroundColor: '#0a0a0a',
      justifyContent: 'center',
      alignItems: 'center',
      padding: 80,
      fontFamily: `'${branding.font || 'IBM Plex Mono'}', monospace`,
    }}>
      {branding.logo_url && (
        <img
          src={branding.logo_url}
          alt="logo"
          style={{
            position: 'absolute',
            top: 48,
            left: 64,
            height: 36,
            objectFit: 'contain',
            opacity: fadeIn(frame, 10),
          }}
        />
      )}
      <div style={{ opacity, transform: `translateY(${y}px)`, textAlign: 'center', maxWidth: 1200 }}>
        <div style={{
          color: accentColor,
          fontSize: 16,
          letterSpacing: 6,
          marginBottom: 32,
          textTransform: 'uppercase',
        }}>
          {branding.company_name || ''}
        </div>
        <div style={{
          color: '#ffffff',
          fontSize: 56,
          fontWeight: 700,
          lineHeight: 1.15,
          marginBottom: 48,
        }}>
          {hook}
        </div>
        <div style={{
          width: 60,
          height: 3,
          backgroundColor: accentColor,
          margin: '0 auto',
          opacity: fadeIn(frame, 15),
        }} />
      </div>
    </AbsoluteFill>
  );
}

// ── Scene: Section slide ──────────────────────────────────────────────────────

function SectionSlide({ section, index, branding, totalSections }) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const accentColor = branding.primary_color || '#ffb000';
  const points = section.talking_points || [];

  return (
    <AbsoluteFill style={{
      backgroundColor: '#0a0a0a',
      padding: '80px 120px',
      fontFamily: `'${branding.font || 'IBM Plex Mono'}', monospace`,
    }}>
      {/* Section counter */}
      <div style={{
        position: 'absolute',
        top: 48,
        right: 64,
        color: 'rgba(255,255,255,0.2)',
        fontSize: 14,
        letterSpacing: 4,
        opacity: fadeIn(frame, 5),
      }}>
        {String(index + 1).padStart(2, '0')} / {String(totalSections).padStart(2, '0')}
      </div>

      {branding.logo_url && (
        <img
          src={branding.logo_url}
          alt="logo"
          style={{
            position: 'absolute',
            top: 48,
            left: 64,
            height: 28,
            objectFit: 'contain',
            opacity: 0.4,
          }}
        />
      )}

      {/* Section heading */}
      <div style={{
        marginTop: 60,
        opacity: fadeIn(frame),
        transform: `translateY(${slideUp(frame)}px)`,
      }}>
        <div style={{
          width: 40,
          height: 3,
          backgroundColor: accentColor,
          marginBottom: 28,
        }} />
        <div style={{
          color: '#ffffff',
          fontSize: 44,
          fontWeight: 700,
          lineHeight: 1.2,
          marginBottom: 48,
          maxWidth: 900,
        }}>
          {section.heading}
        </div>
      </div>

      {/* Talking points */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        {points.map((point, i) => {
          const delay = i * 8;
          return (
            <div key={i} style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: 20,
              opacity: fadeIn(frame, delay + 10),
              transform: `translateY(${slideUp(frame, delay + 10)}px)`,
            }}>
              <div style={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                backgroundColor: accentColor,
                marginTop: 11,
                flexShrink: 0,
              }} />
              <div style={{
                color: '#cccccc',
                fontSize: 26,
                lineHeight: 1.5,
                maxWidth: 1100,
              }}>
                {point}
              </div>
            </div>
          );
        })}
      </div>

      {/* B-ROLL marker */}
      {section.b_roll && (
        <div style={{
          position: 'absolute',
          bottom: 60,
          right: 64,
          color: '#f59e0b',
          fontSize: 13,
          letterSpacing: 3,
          opacity: fadeIn(frame, 20) * 0.7,
          fontStyle: 'italic',
        }}>
          B-ROLL: {section.b_roll}
        </div>
      )}
    </AbsoluteFill>
  );
}

// ── Scene: CTA ────────────────────────────────────────────────────────────────

function CTACard({ cta, branding }) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const accentColor = branding.primary_color || '#ffb000';
  const scale = spring({ frame, fps, config: { mass: 0.6, damping: 12 } });

  return (
    <AbsoluteFill style={{
      backgroundColor: accentColor,
      justifyContent: 'center',
      alignItems: 'center',
      padding: 80,
      fontFamily: `'${branding.font || 'IBM Plex Mono'}', monospace`,
    }}>
      <div style={{
        transform: `scale(${scale})`,
        textAlign: 'center',
        maxWidth: 1000,
      }}>
        <div style={{
          color: '#000000',
          fontSize: 52,
          fontWeight: 700,
          lineHeight: 1.2,
          marginBottom: 32,
        }}>
          {cta}
        </div>
        {branding.logo_url && (
          <img
            src={branding.logo_url}
            alt="logo"
            style={{ height: 48, objectFit: 'contain', marginTop: 20, opacity: 0.8 }}
          />
        )}
      </div>
    </AbsoluteFill>
  );
}

// ── Scene: Credits w/ brand transition ───────────────────────────────────────

function CreditsCard({ branding, target_brand, company_name }) {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  // Transition: start halfway through the credits scene
  const transitionStart = Math.floor(durationInFrames * 0.45);
  const transitionDuration = Math.floor(durationInFrames * 0.3);

  const hasBrandTransition = target_brand && (
    target_brand.primary_color || target_brand.logo_url
  );

  // Interpolate background color from org brand → target brand
  const transitionProgress = hasBrandTransition
    ? interpolate(frame, [transitionStart, transitionStart + transitionDuration], [0, 1], {
        extrapolateLeft: 'clamp',
        extrapolateRight: 'clamp',
      })
    : 0;

  const orgColor = branding.primary_color || '#ffb000';
  const targetColor = hasBrandTransition ? (target_brand.primary_color || orgColor) : orgColor;

  // Simple cross-fade approach — overlay second brand on top
  const orgOpacity = 1 - transitionProgress;
  const targetOpacity = transitionProgress;

  const textOpacity = fadeIn(frame);

  return (
    <AbsoluteFill style={{
      fontFamily: `'${branding.font || 'IBM Plex Mono'}', monospace`,
      overflow: 'hidden',
    }}>
      {/* Org brand layer */}
      <AbsoluteFill style={{
        backgroundColor: orgColor,
        opacity: orgOpacity,
      }} />

      {/* Target brand layer (fades in) */}
      {hasBrandTransition && (
        <AbsoluteFill style={{
          backgroundColor: targetColor,
          opacity: targetOpacity,
        }} />
      )}

      {/* Content */}
      <AbsoluteFill style={{
        justifyContent: 'center',
        alignItems: 'center',
        padding: 80,
      }}>
        {/* Org logo fades out */}
        {branding.logo_url && (
          <img
            src={branding.logo_url}
            alt="logo"
            style={{
              height: 56,
              objectFit: 'contain',
              marginBottom: 24,
              opacity: textOpacity * orgOpacity,
              position: 'absolute',
              top: '35%',
            }}
          />
        )}

        {/* Target logo fades in */}
        {hasBrandTransition && target_brand.logo_url && (
          <img
            src={target_brand.logo_url}
            alt="target logo"
            style={{
              height: 56,
              objectFit: 'contain',
              marginBottom: 24,
              opacity: targetOpacity,
              position: 'absolute',
              top: '35%',
            }}
          />
        )}

        <div style={{
          textAlign: 'center',
          opacity: textOpacity,
          marginTop: 80,
        }}>
          <div style={{
            color: '#000',
            fontSize: 32,
            fontWeight: 700,
            marginBottom: 12,
          }}>
            {hasBrandTransition && target_brand.company_name
              ? `Made for ${target_brand.company_name}`
              : company_name
            }
          </div>
          <div style={{
            color: 'rgba(0,0,0,0.6)',
            fontSize: 18,
            letterSpacing: 3,
          }}>
            pressroomhq.com
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
}

// ── Overlay: Lower third ──────────────────────────────────────────────────────

function LowerThird({ name, title, company, branding }) {
  const frame = useCurrentFrame();
  const accentColor = branding.primary_color || '#ffb000';
  const y = interpolate(frame, [0, 12], [40, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const opacity = fadeIn(frame, 0, 12);

  return (
    <div style={{
      position: 'absolute',
      bottom: 120,
      left: 64,
      opacity,
      transform: `translateY(${y}px)`,
      fontFamily: `'IBM Plex Mono', monospace`,
    }}>
      <div style={{
        display: 'inline-block',
        background: accentColor,
        color: '#000',
        fontSize: 18,
        fontWeight: 700,
        padding: '6px 16px 4px',
        letterSpacing: 1,
      }}>
        {name}
      </div>
      <div style={{
        display: 'inline-block',
        background: 'rgba(0,0,0,0.85)',
        color: '#fff',
        fontSize: 14,
        padding: '6px 16px 4px',
        letterSpacing: 1,
      }}>
        {[title, company].filter(Boolean).join(' · ')}
      </div>
    </div>
  );
}

// ── Overlay: Logo watermark ───────────────────────────────────────────────────

function LogoWatermark({ branding }) {
  const frame = useCurrentFrame();
  if (!branding.logo_url) return null;
  return (
    <div style={{
      position: 'absolute',
      top: 40,
      right: 56,
      opacity: fadeIn(frame, 0, 20) * 0.7,
    }}>
      <img
        src={branding.logo_url}
        alt="logo"
        style={{ height: 32, objectFit: 'contain' }}
      />
    </div>
  );
}

// ── Overlay: Section chyron (topic bug) ───────────────────────────────────────

function SectionChyron({ heading, branding }) {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const accentColor = branding.primary_color || '#ffb000';

  const opacity = interpolate(
    frame,
    [0, 12, durationInFrames - 12, durationInFrames],
    [0, 1, 1, 0],
    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
  );

  return (
    <AbsoluteFill style={{
      justifyContent: 'flex-end',
      alignItems: 'center',
      paddingBottom: 80,
    }}>
      <div style={{
        opacity,
        background: accentColor,
        color: '#000',
        fontSize: 52,
        fontWeight: 700,
        padding: '14px 40px',
        letterSpacing: 4,
        textTransform: 'uppercase',
        fontFamily: `'IBM Plex Mono', monospace`,
        textAlign: 'center',
        maxWidth: '80%',
      }}>
        {heading}
      </div>
    </AbsoluteFill>
  );
}

// ── Overlay: Opening title card (first few seconds) ───────────────────────────

function OverlayTitle({ title, hook, branding }) {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const accentColor = branding.primary_color || '#ffb000';

  // Fade in then fade out
  const opacity = interpolate(
    frame,
    [0, 20, durationInFrames - 20, durationInFrames],
    [0, 1, 1, 0],
    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
  );
  const y = slideUp(frame, 0, 20);

  return (
    <AbsoluteFill style={{
      justifyContent: 'flex-end',
      alignItems: 'center',
      paddingBottom: 80,
      background: 'linear-gradient(to top, rgba(0,0,0,0.75) 0%, transparent 50%)',
    }}>
      <div style={{
        opacity,
        transform: `translateY(${y}px)`,
        textAlign: 'center',
        maxWidth: '85%',
      }}>
        <div style={{
          color: '#fff',
          fontSize: 64,
          fontWeight: 700,
          lineHeight: 1.2,
          fontFamily: `'IBM Plex Mono', monospace`,
          textShadow: '0 2px 12px rgba(0,0,0,0.9)',
        }}>
          {hook || title}
        </div>
        <div style={{
          width: 60,
          height: 4,
          backgroundColor: accentColor,
          margin: '20px auto 0',
        }} />
      </div>
    </AbsoluteFill>
  );
}

// ── Overlay mode composition ──────────────────────────────────────────────────

function OverlayComposition({ data }) {
  const { durationInFrames, fps } = useVideoConfig();
  const branding = data.branding || {};
  const sections = data.sections_detail || [];
  const lowerThirds = data.lower_thirds || [];
  const hook = data.hook || '';
  const title = data.title || '';
  // Resolve footage path: bare filenames come from public/ dir (copy done by render endpoint),
  // absolute paths or URLs pass through as-is.
  const rawFootagePath = data.footage_path || '';
  const footageSrc = rawFootagePath
    ? rawFootagePath.startsWith('http') || rawFootagePath.startsWith('/')
      ? rawFootagePath
      : staticFile(rawFootagePath)   // served from remotion-renderer/public/
    : '';

  // Build section timeline for chyrons
  let sectionOffset = 0;
  const sectionTimeline = sections.map((sec, i) => {
    const frames = s(sec.duration_seconds || 30);
    const entry = { from: sectionOffset, frames, heading: sec.heading, index: i };
    sectionOffset += frames;
    return entry;
  });

  // OBS mode: fully transparent background — exported as webm with alpha channel.
  // No footage, no vignette. User drops this into OBS as a media source over their webcam.
  const isOBS = data.mode === 'obs';

  return (
    <AbsoluteFill style={{ backgroundColor: isOBS ? 'transparent' : '#000' }}>
      {/* Raw footage — baked overlay mode only, not OBS */}
      {!isOBS && footageSrc && (
        <OffthreadVideo
          src={footageSrc}
          style={{ width: '100%', height: '100%', objectFit: 'cover' }}
          onError={() => {/* footage missing — overlays render over black */}}
        />
      )}

      {/* Vignette for legibility — baked mode only (OBS has transparent bg) */}
      {!isOBS && (
      <AbsoluteFill style={{
        background: 'linear-gradient(to top, rgba(0,0,0,0.5) 0%, transparent 40%)',
        pointerEvents: 'none',
      }} />
      )}

      {/* Logo watermark — always visible */}
      <LogoWatermark branding={branding} />

      {/* Opening title overlay — first 6s */}
      <Sequence from={0} durationInFrames={s(6)}>
        <OverlayTitle title={title} hook={hook} branding={branding} />
      </Sequence>

      {/* Section chyrons — topic bug for each section */}
      {sectionTimeline.map((sec) => (
        <Sequence key={sec.index} from={sec.from} durationInFrames={sec.frames}>
          <SectionChyron heading={sec.heading} branding={branding} />
        </Sequence>
      ))}

      {/* Lower thirds — at specified timestamps */}
      {lowerThirds.map((lt, i) => {
        const atFrame = Math.round((lt.at_second || 0) * fps);
        return (
          <Sequence key={i} from={atFrame} durationInFrames={s(5)}>
            <LowerThird
              name={lt.name}
              title={lt.title}
              company={lt.company}
              branding={branding}
            />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
}

// ── Main composition ──────────────────────────────────────────────────────────

export default function YouTubeScript({ data }) {
  if (!data) return null;

  // Overlay mode: footage is background, brand elements layered on top
  // OBS mode: same overlay elements but transparent background, no footage
  if (data.mode === 'overlay' || data.mode === 'obs') {
    return <OverlayComposition data={data} />;
  }

  const branding = data.branding || {};
  const target_brand = data.target_brand || null;
  const sections = data.sections_detail || [];  // full section objects with talking_points
  const hook = data.hook || '';
  const title = data.title || '';
  const cta = data.cta || '';

  let offset = 0;
  const scenes = [];

  const addScene = (durationSecs, Component, props = {}) => {
    const frames = s(durationSecs);
    scenes.push(
      <Sequence key={offset} from={offset} durationInFrames={frames}>
        <Component {...props} />
      </Sequence>
    );
    offset += frames;
  };

  // Hook card — 5 seconds
  addScene(5, HookCard, { hook, title, branding });

  // One slide per section
  sections.forEach((section, i) => {
    const dur = section.duration_seconds || 30;
    addScene(dur, SectionSlide, {
      section,
      index: i,
      branding,
      totalSections: sections.length,
    });
  });

  // CTA — 4 seconds
  addScene(4, CTACard, { cta, branding });

  // Credits with brand transition — 5 seconds
  addScene(5, CreditsCard, {
    branding,
    target_brand,
    company_name: branding.company_name || '',
  });

  return (
    <AbsoluteFill style={{ backgroundColor: '#0a0a0a' }}>
      {scenes}
    </AbsoluteFill>
  );
}
