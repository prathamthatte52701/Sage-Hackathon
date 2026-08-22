import React, { useState, useRef } from "react";

export default function Card3DTilt({ children, className = "", maxTilt = 12 }) {
  const cardRef = useRef(null);
  const [transformStyle, setTransformStyle] = useState("");
  const [glareStyle, setGlareStyle] = useState({ opacity: 0 });

  function handleMouseMove(e) {
    if (!cardRef.current) return;
    const rect = cardRef.current.getBoundingClientRect();
    const width = rect.width;
    const height = rect.height;

    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    const rotateX = ((mouseY - height / 2) / (height / 2)) * -maxTilt;
    const rotateY = ((mouseX - width / 2) / (width / 2)) * maxTilt;

    setTransformStyle(
      `perspective(1000px) rotateX(${rotateX.toFixed(2)}deg) rotateY(${rotateY.toFixed(2)}deg) scale3d(1.02, 1.02, 1.02)`
    );

    setGlareStyle({
      opacity: 0.35,
      background: `radial-gradient(circle at ${mouseX}px ${mouseY}px, rgba(124, 140, 255, 0.25), transparent 70%)`,
    });
  }

  function handleMouseLeave() {
    setTransformStyle("perspective(1000px) rotateX(0deg) rotateY(0deg) scale3d(1, 1, 1)");
    setGlareStyle({ opacity: 0 });
  }

  return (
    <div
      ref={cardRef}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
      className={`relative overflow-hidden transition-transform duration-200 ease-out ${className}`}
      style={{
        transform: transformStyle || "perspective(1000px) rotateX(0deg) rotateY(0deg)",
        transformStyle: "preserve-3d",
      }}
    >
      {/* Dynamic 3D Glare Spotlight */}
      <div
        className="pointer-events-none absolute inset-0 transition-opacity duration-300 z-10"
        style={glareStyle}
      />
      {children}
    </div>
  );
}
