import React, { useRef, useEffect } from "react";

export default function HealthScore3DCanvas({ score = 78.4, size = 180 }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    let animationFrameId;

    let width = (canvas.width = size * 2);
    let height = (canvas.height = size * 2);

    // Color theme based on health score
    let strokeColor = "#36D399";
    let glowColor = "rgba(54, 211, 153, 0.4)";
    if (score < 50) {
      strokeColor = "#FF5D73";
      glowColor = "rgba(255, 93, 115, 0.4)";
    } else if (score < 65) {
      strokeColor = "#F4C95D";
      glowColor = "rgba(244, 201, 93, 0.4)";
    } else if (score < 80) {
      strokeColor = "#7C8CFF";
      glowColor = "rgba(124, 140, 255, 0.4)";
    }

    // Generate 3D Sphere Points
    const numPoints = 120;
    const points = [];
    const radius = size * 0.65;

    for (let i = 0; i < numPoints; i++) {
      const theta = Math.acos(1 - (2 * (i + 0.5)) / numPoints);
      const phi = Math.PI * (1 + Math.sqrt(5)) * i;
      points.push({
        x: radius * Math.sin(theta) * Math.cos(phi),
        y: radius * Math.sin(theta) * Math.sin(phi),
        z: radius * Math.cos(theta),
      });
    }

    let angleX = 0.005;
    let angleY = 0.008;

    function render() {
      ctx.clearRect(0, 0, width, height);

      const centerX = width / 2;
      const centerY = height / 2;

      ctx.save();
      ctx.translate(centerX, centerY);

      // Rotate points in 3D
      points.forEach((p) => {
        // Y-axis rotation
        const cosY = Math.cos(angleY);
        const sinY = Math.sin(angleY);
        const x1 = p.x * cosY - p.z * sinY;
        const z1 = p.z * cosY + p.x * sinY;

        // X-axis rotation
        const cosX = Math.cos(angleX);
        const sinX = Math.sin(angleX);
        const y1 = p.y * cosX - z1 * sinX;
        const z2 = z1 * cosX + p.y * sinX;

        p.x = x1;
        p.y = y1;
        p.z = z2;

        // 3D Perspective Projection
        const fov = 300;
        const scale = fov / (fov + p.z + radius);
        const projX = p.x * scale;
        const projY = p.y * scale;

        const pointRadius = Math.max(1, 2.5 * scale);
        const alpha = Math.max(0.1, (p.z + radius) / (2 * radius));

        ctx.fillStyle = strokeColor;
        ctx.globalAlpha = alpha;
        ctx.shadowBlur = 12;
        ctx.shadowColor = glowColor;

        ctx.beginPath();
        ctx.arc(projX, projY, pointRadius, 0, Math.PI * 2);
        ctx.fill();
      });

      // Draw connecting 3D wireframe edges
      ctx.strokeStyle = strokeColor;
      ctx.lineWidth = 0.6;
      for (let i = 0; i < points.length; i += 3) {
        for (let j = i + 1; j < points.length; j += 4) {
          const distSq =
            Math.pow(points[i].x - points[j].x, 2) +
            Math.pow(points[i].y - points[j].y, 2) +
            Math.pow(points[i].z - points[j].z, 2);

          if (distSq < radius * radius * 0.35) {
            const fov = 300;
            const s1 = fov / (fov + points[i].z + radius);
            const s2 = fov / (fov + points[j].z + radius);

            ctx.globalAlpha = Math.max(0.05, 0.2 * ((points[i].z + radius) / (2 * radius)));
            ctx.beginPath();
            ctx.moveTo(points[i].x * s1, points[i].y * s1);
            ctx.lineTo(points[j].x * s2, points[j].y * s2);
            ctx.stroke();
          }
        }
      }

      ctx.restore();
      animationFrameId = requestAnimationFrame(render);
    }

    render();

    return () => {
      cancelAnimationFrame(animationFrameId);
    };
  }, [score, size]);

  return (
    <div className="relative flex items-center justify-center">
      <canvas
        ref={canvasRef}
        className="w-[180px] h-[180px] pointer-events-none"
        style={{ width: `${size}px`, height: `${size}px` }}
      />
      {/* Central Floating Score */}
      <div className="absolute inset-0 flex flex-col items-center justify-center text-center pointer-events-none">
        <span className="text-3xl font-bold font-mono text-[#F4F7FB] tracking-tight drop-shadow-md">
          {score.toFixed(1)}
        </span>
        <span className="text-[10px] font-mono text-[#9AA4B2] tracking-wider uppercase font-semibold">
          HEALTH SCORE
        </span>
      </div>
    </div>
  );
}
