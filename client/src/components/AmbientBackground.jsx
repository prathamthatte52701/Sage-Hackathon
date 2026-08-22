import React, { useEffect, useRef } from "react";

// Subtle ambient floating orb canvas — no cyberpunk, no particles spam.
// Two slow-drifting gradient orbs that give the hero page visual depth.
export default function AmbientBackground() {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");

    let animId;
    let t = 0;

    function resize() {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    }
    resize();
    window.addEventListener("resize", resize);

    function drawOrb(cx, cy, radius, colorStop1, colorStop2, alpha) {
      const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius);
      grad.addColorStop(0, colorStop1.replace("ALPHA", alpha));
      grad.addColorStop(1, colorStop2);
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(cx, cy, radius, 0, Math.PI * 2);
      ctx.fill();
    }

    function render() {
      t += 0.003;
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      // Orb 1 — drifts top-left to center slowly
      const ox1 = canvas.width * 0.2 + Math.sin(t) * 80;
      const oy1 = canvas.height * 0.25 + Math.cos(t * 0.7) * 60;
      drawOrb(ox1, oy1, 320, "rgba(124,140,255,ALPHA)", "transparent", 0.07);

      // Orb 2 — drifts bottom-right
      const ox2 = canvas.width * 0.78 + Math.cos(t * 0.8) * 100;
      const oy2 = canvas.height * 0.7 + Math.sin(t * 0.6) * 70;
      drawOrb(ox2, oy2, 280, "rgba(54,211,153,ALPHA)", "transparent", 0.055);

      animId = requestAnimationFrame(render);
    }

    render();
    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener("resize", resize);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="fixed inset-0 z-0 pointer-events-none"
      style={{ opacity: 1 }}
    />
  );
}
