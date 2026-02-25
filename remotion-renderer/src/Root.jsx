import React from 'react';
import { Composition, AbsoluteFill, Sequence } from 'remotion';
import DreamFactoryReport from './DreamFactoryReport';
import YouTubeScript from './YouTubeScript';
import AuditReport from './AuditReport';
import BrandChyron from './BrandChyron';

const FPS = 30;

// Default YouTube script data for preview in Remotion Studio
const DEFAULT_YT_DATA = {
  title: 'Preview Script',
  hook: 'Your hook goes here.',
  cta: 'Subscribe for more.',
  branding: {
    primary_color: '#ffb000',
    secondary_color: '',
    logo_url: '',
    font: 'IBM Plex Mono',
    company_name: 'Pressroom HQ',
  },
  target_brand: null,
  sections_detail: [
    {
      heading: 'Section One',
      talking_points: ['First point here.', 'Second point here.'],
      duration_seconds: 30,
      b_roll: '',
    },
  ],
};

// Personalized video: audit reveal → script pitch
function PersonalizedReportComposition({ data }) {
  if (!data) return null;
  const auditData = data.audit_report || {};
  const auditFrames = Math.round((auditData.total_duration_seconds || 40) * FPS);

  return (
    <AbsoluteFill>
      {/* Part 1: Audit reveal */}
      <Sequence from={0} durationInFrames={auditFrames}>
        <AuditReport data={{ branding: auditData.branding || data.branding, scenes: auditData.scenes || {} }} />
      </Sequence>
      {/* Part 2: Script pitch */}
      <Sequence from={auditFrames}>
        <YouTubeScript data={data} />
      </Sequence>
    </AbsoluteFill>
  );
}

export const RemotionRoot = () => {
  return (
    <>
      {/* Audit report — DreamFactory style */}
      <Composition
        id="DreamFactoryReport"
        component={DreamFactoryReport}
        durationInFrames={48 * FPS}
        fps={FPS}
        width={1920}
        height={1080}
      />

      {/* Standalone audit report — data-driven */}
      <Composition
        id="AuditReport"
        component={AuditReport}
        durationInFrames={40 * FPS}
        fps={FPS}
        width={1920}
        height={1080}
        defaultProps={{ data: { branding: { primary_color: '#ffb000', company_name: 'Pressroom HQ' }, scenes: {} } }}
      />

      {/* Personalized outreach — audit reveal + script pitch combined */}
      <Composition
        id="PersonalizedReport"
        component={PersonalizedReportComposition}
        durationInFrames={180 * FPS}
        fps={FPS}
        width={1920}
        height={1080}
        defaultProps={{ data: { ...DEFAULT_YT_DATA, audit_report: null } }}
        calculateMetadata={({ props }) => {
          const data = props.data || {};
          const auditDur = data.audit_report?.total_duration_seconds || 40;
          const sections = data.sections_detail || [];
          const scriptFrames = (5 * FPS) + sections.reduce((sum, s) => sum + ((s.duration_seconds || 30) * FPS), 0) + (4 * FPS) + (5 * FPS);
          return { durationInFrames: Math.round(auditDur * FPS) + Math.max(scriptFrames, 10 * FPS) };
        }}
      />

      {/* YouTube / video script — data-driven via props */}
      <Composition
        id="YouTubeScript"
        component={YouTubeScript}
        durationInFrames={120 * FPS}   // 2 min default; overridden at render time
        fps={FPS}
        width={1920}
        height={1080}
        defaultProps={{ data: DEFAULT_YT_DATA }}
        calculateMetadata={({ props }) => {
          const data = props.data || DEFAULT_YT_DATA;
          // Overlay mode: duration driven by footage_duration_seconds prop (set by backend)
          if (data.mode === 'overlay') {
            const dur = data.footage_duration_seconds || 120;
            return { durationInFrames: Math.round(dur * FPS) };
          }
          // Standard mode: sum up section durations + hook + cta + credits
          const sections = data.sections_detail || [];
          const sectionFrames = sections.reduce((sum, s) => sum + ((s.duration_seconds || 30) * FPS), 0);
          const totalFrames = (5 * FPS) + sectionFrames + (4 * FPS) + (5 * FPS); // hook + sections + cta + credits
          return { durationInFrames: Math.max(totalFrames, 10 * FPS) };
        }}
      />

      {/* Brand chyron — standalone lower-third, transparent bg, webm with alpha.
          Logo left, name + title right. Drop into OBS as a media source. */}
      <Composition
        id="BrandChyron"
        component={BrandChyron}
        durationInFrames={30 * 30}
        fps={30}
        width={1920}
        height={1080}
        defaultProps={{
          data: {
            name: 'Nic Davidson',
            title: 'Head of Engineering',
            logo_url: '',
            accent_color: '#ffb000',
            duration_seconds: 30,
          }
        }}
        calculateMetadata={({ props }) => ({
          durationInFrames: Math.round((props.data?.duration_seconds || 30) * 30),
        })}
      />

      {/* OBS overlay — transparent background, no footage, alpha channel webm export.
          Duration matches the script so it syncs frame-perfect in OBS.
          User records themselves live; this plays on top as a browser/media source. */}
      <Composition
        id="OBSOverlay"
        component={YouTubeScript}
        durationInFrames={120 * FPS}
        fps={FPS}
        width={1920}
        height={1080}
        defaultProps={{ data: { ...DEFAULT_YT_DATA, mode: 'obs' } }}
        calculateMetadata={({ props }) => {
          const data = props.data || DEFAULT_YT_DATA;
          const sections = data.sections_detail || [];
          const sectionFrames = sections.reduce((sum, s) => sum + ((s.duration_seconds || 30) * FPS), 0);
          // hook (5s) + sections + cta (4s) + credits (5s)
          const totalFrames = (5 * FPS) + sectionFrames + (4 * FPS) + (5 * FPS);
          return { durationInFrames: Math.max(totalFrames, 10 * FPS) };
        }}
      />
    </>
  );
};
