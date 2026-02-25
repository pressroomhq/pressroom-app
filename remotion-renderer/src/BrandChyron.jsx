import React from 'react';
import {
  AbsoluteFill,
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  spring,
  Img,
  staticFile,
} from 'remotion';

// Slides up from bottom, holds, optional fade at end
export default function BrandChyron({ data }) {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  const name = data?.name || 'Nic Davidson';
  const title = data?.title || 'Head of Engineering';
  const logoUrl = data?.logo_url || '';
  const accentColor = data?.accent_color || '#ffb000';
  const holdStart = 20; // frames before fully visible

  // Slide up from offscreen
  const y = interpolate(frame, [0, holdStart], [120, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  // Fade in
  const opacity = interpolate(frame, [0, holdStart], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill style={{ backgroundColor: 'transparent' }}>
      {/* Lower-left chyron */}
      <div style={{
        position: 'absolute',
        bottom: 80,
        left: 72,
        display: 'flex',
        alignItems: 'center',
        gap: 0,
        opacity,
        transform: `translateY(${y}px)`,
      }}>
        {/* Accent bar */}
        <div style={{
          width: 8,
          alignSelf: 'stretch',
          backgroundColor: accentColor,
          flexShrink: 0,
        }} />

        {/* Logo block */}
        {logoUrl ? (
          <div style={{
            backgroundColor: 'rgba(0,0,0,0.88)',
            padding: '18px 24px',
            display: 'flex',
            alignItems: 'center',
          }}>
            <Img
              src={logoUrl}
              style={{
                height: 44,
                width: 'auto',
                objectFit: 'contain',
              }}
            />
          </div>
        ) : null}

        {/* Name + title block */}
        <div style={{
          backgroundColor: 'rgba(0,0,0,0.88)',
          padding: '18px 36px 18px 28px',
          borderLeft: logoUrl ? '1px solid rgba(255,255,255,0.1)' : 'none',
        }}>
          <div style={{
            color: '#ffffff',
            fontSize: 36,
            fontWeight: 700,
            fontFamily: `'IBM Plex Mono', monospace`,
            letterSpacing: 1,
            lineHeight: 1.2,
            whiteSpace: 'nowrap',
          }}>
            {name}
          </div>
          <div style={{
            color: accentColor,
            fontSize: 22,
            fontWeight: 400,
            fontFamily: `'IBM Plex Mono', monospace`,
            letterSpacing: 2,
            marginTop: 4,
            textTransform: 'uppercase',
            whiteSpace: 'nowrap',
          }}>
            {title}
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
}
