import React from "react";
import { AbsoluteFill } from "remotion";
import { EASE, ramp, scene, type SceneName } from "../lib/anim";
import { C, FONT } from "../lib/theme";

const COPY: Record<SceneName, string> = {
  open: "场景一",
  main: "场景二",
  end: "场景三",
};

const Card: React.FC<{ t: number; name: SceneName }> = ({ t, name }) => {
  const s = scene(name);
  if (t < s.start || t >= s.end) return null;
  const inP = ramp(t, [s.start, s.start + 0.6]);
  const out = ramp(t, [s.end - 0.3, s.end], [0, 1], EASE.in);
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
      <div
        style={{
          fontFamily: FONT.display,
          fontSize: 120,
          color: C.fg,
          opacity: inP * (1 - out),
          transform: `translateY(${(1 - inP) * 40}px) scale(${1 + out * 0.1})`,
        }}
      >
        {COPY[name]}
      </div>
    </AbsoluteFill>
  );
};

export const Example: React.FC<{ t: number }> = ({ t }) => (
  <>
    {(Object.keys(COPY) as SceneName[]).map((name) => (
      <Card key={name} t={t} name={name} />
    ))}
  </>
);
