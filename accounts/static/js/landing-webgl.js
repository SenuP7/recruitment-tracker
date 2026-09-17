/* Slow aurora / light-field drift for the Candidflow landing page.
   A single full-screen shader plane. Broad, soft bands of light move
   through the slate palette via domain-warped fBm noise -- one continuous
   surface, so there are no points, grain or discrete elements anywhere.
   A tiny ordered dither (~1/255) is applied at the end: on dark gradients
   8-bit colour quantisation produces visible banding, and the dither
   removes it without being perceptible itself. */
(function () {
  if (typeof THREE === "undefined") return;

  var canvas = document.getElementById("webgl-bg");
  if (!canvas) return;

  var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

  var scene = new THREE.Scene();
  var camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);

  var uniforms = {
    uTime: { value: 0 },
    uAspect: { value: window.innerWidth / window.innerHeight },
  };

  var material = new THREE.ShaderMaterial({
    uniforms: uniforms,
    vertexShader: [
      "varying vec2 vUv;",
      "void main() {",
      "  vUv = uv;",
      "  gl_Position = vec4(position, 1.0);",
      "}",
    ].join("\n"),
    fragmentShader: [
      "precision highp float;",
      "uniform float uTime;",
      "uniform float uAspect;",
      "varying vec2 vUv;",

      // Value noise + fBm. Smooth by construction -- no point sampling.
      "vec2 hash22(vec2 p) {",
      "  p = vec2(dot(p, vec2(127.1, 311.7)), dot(p, vec2(269.5, 183.3)));",
      "  return fract(sin(p) * 43758.5453123) * 2.0 - 1.0;",
      "}",
      "float gnoise(vec2 p) {",
      "  vec2 i = floor(p);",
      "  vec2 f = fract(p);",
      "  vec2 u = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);",
      "  return mix(mix(dot(hash22(i + vec2(0.0, 0.0)), f - vec2(0.0, 0.0)),",
      "                 dot(hash22(i + vec2(1.0, 0.0)), f - vec2(1.0, 0.0)), u.x),",
      "             mix(dot(hash22(i + vec2(0.0, 1.0)), f - vec2(0.0, 1.0)),",
      "                 dot(hash22(i + vec2(1.0, 1.0)), f - vec2(1.0, 1.0)), u.x), u.y);",
      "}",
      "float fbm(vec2 p) {",
      "  float v = 0.0;",
      "  float a = 0.5;",
      "  for (int i = 0; i < 4; i++) {",
      "    v += a * gnoise(p);",
      "    p *= 2.02;",
      "    a *= 0.5;",
      "  }",
      "  return v;",
      "}",

      "void main() {",
      "  vec2 uv = vUv;",
      "  uv.x *= uAspect;",
      "  float t = uTime * 0.02;",

      // Domain warp: bends the bands into soft organic sweeps rather than
      // straight stripes, which is what reads as "aurora" instead of "gradient".
      "  vec2 q = vec2(fbm(uv * 1.1 + vec2(0.0, t)), fbm(uv * 1.1 + vec2(4.7, -t)));",
      "  vec2 r = vec2(fbm(uv * 1.4 + q * 1.6 + vec2(1.7, 9.2) + t * 0.6),",
      "                fbm(uv * 1.4 + q * 1.6 + vec2(8.3, 2.8) - t * 0.4));",
      "  float band = fbm(uv * 1.25 + r * 1.4);",
      "  band = smoothstep(-0.55, 0.65, band);",

      // A second, slower field so brightness never settles into one shape.
      "  float glow = smoothstep(-0.3, 0.8, fbm(uv * 0.75 + vec2(t * 0.5, -t * 0.3)));",

      "  vec3 base    = vec3(0.024, 0.078, 0.106);", // #06141b
      "  vec3 deep    = vec3(0.067, 0.129, 0.125);", // #112120
      "  vec3 mid     = vec3(0.145, 0.216, 0.271);", // #253745
      "  vec3 lift    = vec3(0.290, 0.361, 0.416);", // #4a5c6a

      "  vec3 col = mix(base, deep, band);",
      "  col = mix(col, mid, smoothstep(0.35, 1.0, band) * 0.85);",
      "  col = mix(col, lift, smoothstep(0.72, 1.0, band * glow) * 0.5);",

      // Gentle vignette so the centre stays calm behind content.
      "  vec2 c = vUv - 0.5;",
      "  col *= 1.0 - dot(c, c) * 0.35;",

      // Ordered dither -- kills 8-bit banding in the dark gradient.
      "  float d = fract(sin(dot(gl_FragCoord.xy, vec2(12.9898, 78.233))) * 43758.5453);",
      "  col += (d - 0.5) / 255.0;",

      "  gl_FragColor = vec4(col, 1.0);",
      "}",
    ].join("\n"),
  });

  var mesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), material);
  scene.add(mesh);

  function resize() {
    var w = window.innerWidth;
    var h = window.innerHeight;
    renderer.setSize(w, h);
    uniforms.uAspect.value = w / h;
  }
  resize();
  window.addEventListener("resize", resize);

  var clock = new THREE.Clock();
  function animate() {
    requestAnimationFrame(animate);
    if (!reduceMotion) uniforms.uTime.value = clock.getElapsedTime();
    renderer.render(scene, camera);
  }
  animate();
})();
