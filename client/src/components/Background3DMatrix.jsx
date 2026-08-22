import React, { useRef, useEffect } from "react";

export default function Background3DMatrix() {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    let animationFrameId;

    function resize() {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    }
    resize();
    window.addEventListener("resize", resize);

    // Create 3D Floating Particles
    const count = 50;
    const particles = [];
    for (let i = 0; i < count; i++) {
      particles.push({
        x: (Math.random() - 0.5) * canvas.width * 1.5,
        y: (Math.random() - 0.5) * canvas.height * 1.5,
        z: Math.random() * 800,
        radius: Math.random() * 2 + 1,
        vx: (Math.random() - 0.5) * 0.3,
        vy: (Math.random() - 0.5) * 0.3,
        vz: (Math.random() - 0.5) * 0.5,
      });
    }

    function render() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      const centerX = canvas.width / 2;
      const centerY = canvas.height / 2;
      const fov = 400;

      ctx.fillStyle = "#7C8CFF";
      ctx.strokeStyle = "rgba(124, 140, 255, 0.08)";
      ctx.lineWidth = 0.5;

      particles.forEach((p, idx) => {
        p.x += p.vx;
        p.y += p.vy;
        p.z += p.vz;

        if (p.z <= 0) p.z = 800;
        if (p.z > 800) p.z = 0;

        const scale = fov / (fov + p.z);
        const screenX = centerX + p.x * scale;
        const screenY = centerY + p.y * scale;
        const alpha = (1 - p.z / 800) * 0.35;

        if (screenX >= 0 && screenX <= canvas.width && screenY >= 0 && screenY <= canvas.height) {
          ctx.globalAlpha = alpha;
          ctx.beginPath();
          ctx.arc(screenX, screenY, p.radius * scale, 0, Math.PI * 2);
          ctx.fill();

          // Draw faint 3D connection lines to near particles
          for (let j = idx + 1; j < particles.length; j++) {
            const p2 = particles[j];
            const distSq =
              Math.pow(p.x - p2.x, 2) + Math.pow(p.y - p2.y, 2) + Math.pow(p.z - p2.z, 2);
            if (distSq < 180 * 180) {
              const scale2 = fov / (fov + p2.z);
              const screenX2 = centerX + p2.x * scale2;
              const screenY2 = centerY + p2.y * scale2;

              ctx.globalAlpha = alpha * 0.15;
              ctx.beginPath();
              ctx.moveTo(screenX, screenY);
              ctx.lineTo(screenX2, screenY2);
              ctx.stroke();
            }
          }
        }
      });

      animationFrameId = requestAnimationFrame(render);
    }

    render();

    return () => {
      window.removeEventListener("resize", resize);
      cancelAnimationFrame(animationFrameId);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="fixed inset-0 pointer-events-none z-0 opacity-40"
    />
  );
}
