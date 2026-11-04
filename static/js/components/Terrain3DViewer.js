import { html, React } from '../html.js';

const { useState, useEffect, useRef } = React;

/**
 * Terrain3DViewer: High-performance 3D elevation mesh viewer powered by Three.js.
 * Visualizes ALL landscapes: Mountains, Sand Dunes, Deserts, Canyons, Roads, and Cities.
 * Features:
 * - Dynamic hypsometric palettes (Desert Sand, Topographic, Urban)
 * - True-color satellite image texture draping (drapes aerial photos over 3D terrain)
 * - Interactive 3D Transect Profiler: Click Point A & B on the 3D model to slice an instant elevation cross-section!
 * - 100% CPU / Integrated Graphics friendly (<700KB heightmap, 60 FPS without GPU).
 */
export function Terrain3DViewer({
  isOpen,
  onClose,
  payloadUrl,
  availableTextures = [],
  title = '3D Digital Elevation Model',
}) {
  const mountRef = useRef(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [meta, setMeta] = useState(null);
  const [exaggeration, setExaggeration] = useState(1.8);
  const [wireframe, setWireframe] = useState(false);
  const [surfaceMode, setSurfaceMode] = useState('desert'); // 'lidar_canopy', 'lidar_discrete', 'desert', 'topographic', 'urban', or specific image URL
  const [renderMode, setRenderMode] = useState('surface'); // 'surface' | 'points'
  const [measuring, setMeasuring] = useState(false);
  const [transectResult, setTransectResult] = useState(null);

  // References to Three.js objects
  const sceneRef = useRef(null);
  const meshRef = useRef(null);
  const pointsRef = useRef(null);
  const rendererRef = useRef(null);
  const animFrameRef = useRef(null);
  const cameraRef = useRef(null);
  const rawElevationsRef = useRef(null);
  const rawHillshadeRef = useRef(null);

  // Interaction state
  const isDraggingRef = useRef(false);
  const isRightDragRef = useRef(false);
  const clickStartPosRef = useRef({ x: 0, y: 0 });
  const prevMouseRef = useRef({ x: 0, y: 0 });
  const rotationRef = useRef({ x: 0.65, y: -0.75 });
  const panRef = useRef({ x: 0, y: -20 });
  const zoomRef = useRef(260);

  // Transect raycasting refs
  const transectPointsRef = useRef([]);
  const transectObjectsRef = useRef([]);

  useEffect(() => {
    if (!isOpen || !payloadUrl) return;

    let isMounted = true;
    setLoading(true);
    setError(null);
    clearTransect();

    fetch(payloadUrl)
      .then((res) => {
        if (!res.ok) throw new Error(`Failed to load 3D terrain payload (${res.status})`);
        return res.json();
      })
      .then((data) => {
        if (!isMounted) return;
        setMeta(data);
        rawElevationsRef.current = data.elevations;
        rawHillshadeRef.current = data.hillshade;
        const isLidar = data.is_lidar || (data.source || '').toLowerCase().includes('lidar') || (data.source || '').toLowerCase().includes('chm');
        const initialTheme = data.orthophoto_url ? data.orthophoto_url : (isLidar ? 'realistic_urban' : (data.default_surface || 'desert'));
        setSurfaceMode(initialTheme);
        initThreeScene(data, initialTheme);
        setLoading(false);
      })
      .catch((err) => {
        if (isMounted) {
          setError(err.message);
          setLoading(false);
        }
      });

    return () => {
      isMounted = false;
      cleanupThree();
    };
  }, [isOpen, payloadUrl]);

  // Dynamic renderMode toggle (Solid Surface vs Point Cloud)
  useEffect(() => {
    if (meshRef.current) meshRef.current.visible = (renderMode === 'surface');
    if (pointsRef.current) pointsRef.current.visible = (renderMode === 'points');
  }, [renderMode]);

  // Dynamic exaggeration update without reconstructing the scene
  useEffect(() => {
    if (!meshRef.current || !rawElevationsRef.current || !meta) return;
    updateElevationVertices(exaggeration);
  }, [exaggeration]);

  // Dynamic wireframe toggle
  useEffect(() => {
    if (meshRef.current && meshRef.current.material) {
      meshRef.current.material.wireframe = wireframe;
    }
  }, [wireframe]);

  // Surface mode change (LiDAR, Desert, Topographic, Urban, or Satellite Texture Drape)
  useEffect(() => {
    if (!meshRef.current || !meta) return;
    applySurfaceMode(surfaceMode);
  }, [surfaceMode]);

  const cleanupThree = () => {
    if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    clearTransect();
    if (rendererRef.current && rendererRef.current.domElement) {
      const parent = rendererRef.current.domElement.parentNode;
      if (parent) parent.removeChild(rendererRef.current.domElement);
      rendererRef.current.dispose();
    }
    if (meshRef.current) {
      if (meshRef.current.geometry) meshRef.current.geometry.dispose();
      if (meshRef.current.material) {
        if (meshRef.current.material.map) meshRef.current.material.map.dispose();
        meshRef.current.material.dispose();
      }
    }
    if (pointsRef.current) {
      if (pointsRef.current.material) pointsRef.current.material.dispose();
      pointsRef.current = null;
    }
    sceneRef.current = null;
    meshRef.current = null;
    rendererRef.current = null;
  };

  const clearTransect = () => {
    transectPointsRef.current = [];
    setTransectResult(null);
    if (sceneRef.current && transectObjectsRef.current.length > 0) {
      transectObjectsRef.current.forEach((obj) => sceneRef.current.remove(obj));
      transectObjectsRef.current = [];
    }
  };

  const updateElevationVertices = (exagg) => {
    const mesh = meshRef.current;
    const elevs = rawElevationsRef.current;
    if (!mesh || !elevs || !meta) return;

    const pos = mesh.geometry.attributes.position;
    const isLidar = meta.is_lidar || (meta.source || '').toLowerCase().includes('lidar') || (meta.source || '').toLowerCase().includes('chm');
    const minZ = meta.min_elevation_m;
    // Ground level anchor: for LiDAR CHM, ground is strictly 0.0
    const effectiveMinZ = isLidar ? Math.max(0.0, minZ) : Math.max(-500.0, minZ);

    let rangeZ = meta.elevation_range_m;
    // Guard against corrupt range from unmasked nodata sentinels
    if (rangeZ > 5000.0 && isLidar) {
      rangeZ = 60.0;
    } else {
      rangeZ = Math.max(rangeZ, 1.0);
    }
    const zScale = (45.0 / rangeZ) * exagg;

    for (let i = 0; i < elevs.length; i++) {
      const e = elevs[i];
      // Sanitize nodata / boundary sentinels (e.g. -9999 or negative CHM)
      const validElev = (e < -500.0 || (isLidar && e < 0.0)) ? effectiveMinZ : e;
      const zVal = Math.max(0.0, (validElev - effectiveMinZ) * zScale);
      pos.setZ(i, zVal);
    }
    pos.needsUpdate = true;
    mesh.geometry.computeVertexNormals();
  };

  const computeColorsForTheme = (themeName, data) => {
    const isLidar = data.is_lidar || (data.source || '').toLowerCase().includes('lidar') ||
                    (data.source || '').toLowerCase().includes('chm') || data.elevation_range_m < 90;
    const minZ = data.min_elevation_m;
    const effectiveMinZ = isLidar ? Math.max(0.0, minZ) : Math.max(-500.0, minZ);
    let rangeZ = data.elevation_range_m;
    if (rangeZ > 5000.0 && isLidar) rangeZ = 60.0;
    rangeZ = Math.max(rangeZ, 1.0);

    const elevs = data.elevations;
    const hillshade = data.hillshade || [];
    const colors = new Float32Array(elevs.length * 3);

    for (let i = 0; i < elevs.length; i++) {
      const e = elevs[i];
      const safeElev = (e < -500.0 || (isLidar && e < 0.0)) ? effectiveMinZ : e;
      const normZ = Math.max(0, Math.min(1, (safeElev - effectiveMinZ) / rangeZ));
      const hs = (hillshade[i] !== undefined ? hillshade[i] : 180) / 255.0;

      let r = 0, g = 0, b = 0;
      if (themeName === 'realistic_urban') {
        // Full-structure photorealistic palette.
        // Uses absolute above-ground height (metres) so every structure type
        // gets a distinct, physically meaningful colour band.
        const hM = isLidar ? Math.max(0.0, safeElev - effectiveMinZ) : normZ * 58.0;

        // Hillshade drives the shading contrast — stronger multiplier so building
        // walls and mountain faces read as clearly different from flat surfaces.
        const shade = 0.25 + 0.75 * hs;

        if (hM < 0.5) {
          // Ground: roads, car parks, plazas — dark charcoal asphalt
          r = 0.18; g = 0.20; b = 0.23;
        } else if (hM < 1.5) {
          // Low ground cover: kerbs, walkways, bare soil — warm grey
          r = 0.36; g = 0.33; b = 0.28;
        } else if (hM < 3.0) {
          // Lawn, park grass, low shrubs — natural muted green
          r = 0.24 + hs * 0.06; g = 0.52 + hs * 0.12; b = 0.18 + hs * 0.04;
        } else if (hM < 7.0) {
          // Low to mid buildings (1–2 storey), dense shrubs — concrete beige / muted olive
          const t = (hM - 3.0) / 4.0;
          r = 0.58 + t * 0.10; g = 0.52 + t * 0.04; b = 0.42 - t * 0.08;
        } else if (hM < 14.0) {
          // Mid-height tree canopy and understory (3–5 storey equiv) — rich forest green
          const t = (hM - 7.0) / 7.0;
          r = 0.10 + t * 0.04; g = 0.44 - t * 0.08; b = 0.14 - t * 0.03;
        } else if (hM < 22.0) {
          // Tall buildings (5–8 storey), upper canopy — steel blue-grey concrete
          const t = (hM - 14.0) / 8.0;
          r = 0.52 + t * 0.12; g = 0.54 + t * 0.10; b = 0.60 + t * 0.08;
        } else if (hM < 35.0) {
          // Large structures: stadium stands, arena roof, tall towers — warm terracotta brick
          const t = (hM - 22.0) / 13.0;
          r = 0.80 + t * 0.08; g = 0.38 - t * 0.06; b = 0.14 - t * 0.04;
        } else {
          // Extreme height: very tall structures, mountain peaks — pale stone / granite
          r = 0.78; g = 0.74; b = 0.70;
        }

        // Apply shade factor after colour selection
        r *= shade; g *= shade; b *= shade;
      } else if (themeName === 'lidar_canopy') {
        // LiDAR Canopy, Road & Building Palette — fine-grained height bands
        const isLidar = data.is_lidar || (data.source || '').toLowerCase().includes('lidar') ||
                        (data.source || '').toLowerCase().includes('chm') || data.elevation_range_m < 90;
        const hM = isLidar ? (elevs[i] - minZ) : normZ * 58.0;
        const shade = 0.28 + 0.72 * hs;

        if (hM < 0.5) {
          // Flat Ground, Roads, Parking — near-black charcoal asphalt
          r = 0.18; g = 0.22; b = 0.26;
        } else if (hM < 1.2) {
          // Bare soil, gravel, unpaved paths
          r = 0.48; g = 0.40; b = 0.30;
        } else if (hM < 2.8) {
          // Lawn, grass, low ground cover — lime green
          r = 0.38; g = 0.72; b = 0.18;
        } else if (hM < 6.0) {
          // Shrubs, hedges, low understorey — mid green
          r = 0.14; g = 0.58; b = 0.22;
        } else if (hM < 14.0) {
          // Main forest canopy, mid-height trees — deep forest green
          const t = (hM - 6.0) / 8.0;
          r = 0.08 + t * 0.02; g = 0.46 - t * 0.08; b = 0.18 - t * 0.04;
        } else if (hM < 22.0) {
          // Tall trees, emergent canopy — very dark green / near-black crown tops
          r = 0.06; g = 0.32; b = 0.12;
        } else if (hM < 35.0) {
          // Built structures: walls, columns, lower stadium tiers — warm sandstone
          const t = (hM - 22.0) / 13.0;
          r = 0.78 + t * 0.10; g = 0.60 + t * 0.04; b = 0.32 - t * 0.08;
        } else {
          // Roof tops, upper stadium bowl, tall building crowns — terracotta / burnt orange
          r = 0.90; g = 0.42; b = 0.10;
        }

        r *= shade; g *= shade; b *= shade;
      } else if (themeName === 'lidar_discrete') {
        // Discrete 3-class: Ground / Vegetation / Structures — maximum contrast
        const isLidar = data.is_lidar || (data.source || '').toLowerCase().includes('lidar') ||
                        (data.source || '').toLowerCase().includes('chm') || data.elevation_range_m < 90;
        const hM = isLidar ? (elevs[i] - minZ) : normZ * 58.0;
        const shade = 0.30 + 0.70 * hs;
        if (hM < 1.0) {
          // Ground / Road / Parking — dark slate
          r = 0.22; g = 0.28; b = 0.35;
        } else if (hM < 22.0) {
          // All vegetation — vivid emerald green
          r = 0.04; g = 0.70; b = 0.46;
        } else {
          // All built structures — saturated amber
          r = 0.96; g = 0.62; b = 0.06;
        }
        r *= shade; g *= shade; b *= shade;
      } else if (themeName === 'desert') {
        // Desert sand & dunes -> canyon rock -> dark mountain peaks
        if (normZ < 0.25) {
          const t = normZ / 0.25;
          r = 0.92 - t * 0.08;
          g = 0.76 - t * 0.14;
          b = 0.48 - t * 0.20;
        } else if (normZ < 0.65) {
          const t = (normZ - 0.25) / 0.40;
          r = 0.84 - t * 0.24;
          g = 0.62 - t * 0.24;
          b = 0.28 - t * 0.10;
        } else {
          const t = (normZ - 0.65) / 0.35;
          r = 0.60 - t * 0.25;
          g = 0.38 - t * 0.16;
          b = 0.18 + t * 0.04;
        }
      } else if (themeName === 'urban') {
        // Urban / roads / concrete built-up contrast
        if (normZ < 0.30) {
          const t = normZ / 0.30;
          r = 0.35 + t * 0.15;
          g = 0.40 + t * 0.15;
          b = 0.45 + t * 0.15;
        } else {
          const t = (normZ - 0.30) / 0.70;
          r = 0.50 + t * 0.25;
          g = 0.55 + t * 0.20;
          b = 0.60 + t * 0.15;
        }
      } else {
        // Standard Topographic (green valley -> sand foothills -> brown mountains -> snow white)
        if (normZ < 0.20) {
          const t = normZ / 0.20;
          r = 0.15 + t * 0.25;
          g = 0.50 + t * 0.15;
          b = 0.25 - t * 0.10;
        } else if (normZ < 0.55) {
          const t = (normZ - 0.20) / 0.35;
          r = 0.40 + t * 0.32;
          g = 0.65 + t * 0.05;
          b = 0.15 + t * 0.15;
        } else if (normZ < 0.85) {
          const t = (normZ - 0.55) / 0.30;
          r = 0.72 - t * 0.20;
          g = 0.70 - t * 0.32;
          b = 0.30 - t * 0.05;
        } else {
          const t = (normZ - 0.85) / 0.15;
          r = 0.52 + t * 0.43;
          g = 0.38 + t * 0.57;
          b = 0.25 + t * 0.70;
        }
      }

      const shadeFactor = 0.35 + 0.65 * hs;
      colors[i * 3 + 0] = Math.min(1.0, r * shadeFactor);
      colors[i * 3 + 1] = Math.min(1.0, g * shadeFactor);
      colors[i * 3 + 2] = Math.min(1.0, b * shadeFactor);
    }
    return colors;
  };

  const applySurfaceMode = (mode) => {
    const THREE = window.THREE;
    const mesh = meshRef.current;
    if (!THREE || !mesh || !meta) return;

    if (['realistic_urban', 'lidar_canopy', 'lidar_discrete', 'desert', 'topographic', 'urban'].includes(mode)) {
      const colors = computeColorsForTheme(mode, meta);
      mesh.geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
      mesh.geometry.attributes.color.needsUpdate = true;
      if (mesh.material.map) {
        mesh.material.map.dispose();
        mesh.material.map = null;
      }
      mesh.material = new THREE.MeshLambertMaterial({
        vertexColors: true,
        side: THREE.DoubleSide,
        wireframe: wireframe,
      });
      mesh.material.needsUpdate = true;
    } else {
      // mode is an image texture URL (e.g. true-color RGB satellite image or landcover map)
      const loader = new THREE.TextureLoader();
      loader.load(mode, (tex) => {
        tex.colorSpace = THREE.SRGBColorSpace;
        mesh.material = new THREE.MeshLambertMaterial({
          map: tex,
          side: THREE.DoubleSide,
          wireframe: wireframe,
        });
        mesh.material.needsUpdate = true;
      });
    }
  };

  const initThreeScene = (data, initialMode) => {
    const THREE = window.THREE;
    if (!THREE) {
      setError('Three.js library is not loaded');
      return;
    }

    const container = mountRef.current;
    if (!container) return;

    container.innerHTML = '';

    const width = container.clientWidth || 800;
    const height = container.clientHeight || 520;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0b1120);
    sceneRef.current = scene;

    const camera = new THREE.PerspectiveCamera(40, width / height, 1, 3000);
    cameraRef.current = camera;

    const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'low-power' });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
    container.appendChild(renderer.domElement);
    rendererRef.current = renderer;

    // Three-point lighting: ambient fill + strong sun + soft fill from opposite side
    // Strong directional contrast makes building walls, roof edges, and tree crowns
    // read as distinct 3D shapes rather than a flat-coloured surface.
    const ambientLight = new THREE.AmbientLight(0xd0e4ff, 0.45);
    scene.add(ambientLight);

    // Primary sun — angled to cast shadows across building walls and canyon faces
    const dirLight = new THREE.DirectionalLight(0xfff5e0, 1.2);
    dirLight.position.set(-180, 320, 160);
    scene.add(dirLight);

    // Secondary soft fill from the opposite side — lifts shadow areas so walls
    // don't go completely black, revealing building detail in shadow zones
    const fillLight = new THREE.DirectionalLight(0xaaccff, 0.35);
    fillLight.position.set(160, 100, -180);
    scene.add(fillLight);

    const gridW = data.width;
    const gridH = data.height;
    const meshSize = 200;

    const geometry = new THREE.PlaneGeometry(meshSize, meshSize * (gridH / gridW), gridW - 1, gridH - 1);
    const isBuiltInTheme = ['realistic_urban', 'lidar_canopy', 'lidar_discrete', 'desert', 'topographic', 'urban'].includes(initialMode);
    const colors = computeColorsForTheme(isBuiltInTheme ? initialMode : 'lidar_canopy', data);
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));

    const material = new THREE.MeshLambertMaterial({
      vertexColors: true,
      side: THREE.DoubleSide,
      wireframe: wireframe,
    });

    const mesh = new THREE.Mesh(geometry, material);
    mesh.rotation.x = -Math.PI / 2;
    mesh.visible = (renderMode === 'surface');
    scene.add(mesh);
    meshRef.current = mesh;

    // Discrete 3D Point Cloud returns
    const pointsMaterial = new THREE.PointsMaterial({
      size: 3.2,
      vertexColors: true,
      sizeAttenuation: true,
    });
    const points = new THREE.Points(geometry, pointsMaterial);
    points.rotation.x = -Math.PI / 2;
    points.visible = (renderMode === 'points');
    scene.add(points);
    pointsRef.current = points;

    updateElevationVertices(exaggeration);

    if (initialMode && !isBuiltInTheme) {
      applySurfaceMode(initialMode);
    }

    camera.position.set(0, 160, zoomRef.current);
    camera.lookAt(0, 0, 0);

    const animate = () => {
      animFrameRef.current = requestAnimationFrame(animate);

      if (meshRef.current) {
        meshRef.current.rotation.x = -Math.PI / 2 + rotationRef.current.x;
        meshRef.current.rotation.z = rotationRef.current.y;
        meshRef.current.position.x = panRef.current.x;
        meshRef.current.position.y = panRef.current.y;
      }

      if (pointsRef.current) {
        pointsRef.current.rotation.x = -Math.PI / 2 + rotationRef.current.x;
        pointsRef.current.rotation.z = rotationRef.current.y;
        pointsRef.current.position.x = panRef.current.x;
        pointsRef.current.position.y = panRef.current.y;
      }

      renderer.render(scene, camera);
    };
    animate();
  };

  const handleMouseDown = (e) => {
    isDraggingRef.current = true;
    isRightDragRef.current = e.button === 2;
    clickStartPosRef.current = { x: e.clientX, y: e.clientY };
    prevMouseRef.current = { x: e.clientX, y: e.clientY };
  };

  const handleMouseMove = (e) => {
    if (!isDraggingRef.current) return;
    const dx = e.clientX - prevMouseRef.current.x;
    const dy = e.clientY - prevMouseRef.current.y;
    prevMouseRef.current = { x: e.clientX, y: e.clientY };

    if (isRightDragRef.current) {
      panRef.current.x += dx * 0.3;
      panRef.current.y -= dy * 0.3;
    } else {
      rotationRef.current.y += dx * 0.008;
      rotationRef.current.x = Math.max(-0.2, Math.min(1.4, rotationRef.current.x + dy * 0.008));
    }
  };

  const handleMouseUp = (e) => {
    isDraggingRef.current = false;

    // Check if this was a clean click (not a camera drag) while in measuring mode
    const distMoved = Math.hypot(e.clientX - clickStartPosRef.current.x, e.clientY - clickStartPosRef.current.y);
    if (distMoved < 5 && measuring) {
      handleMeshClick(e);
    }
  };

  const handleWheel = (e) => {
    e.preventDefault();
    zoomRef.current = Math.max(80, Math.min(600, zoomRef.current + e.deltaY * 0.35));
    if (cameraRef.current) {
      cameraRef.current.position.z = zoomRef.current;
      cameraRef.current.position.y = zoomRef.current * 0.65;
    }
  };

  // Raycaster click handler for interactive transect measurement
  const handleMeshClick = (e) => {
    const THREE = window.THREE;
    if (!THREE || !meshRef.current || !cameraRef.current || !mountRef.current || !meta) return;

    const rect = mountRef.current.getBoundingClientRect();
    const mouse = new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1
    );

    const raycaster = new THREE.Raycaster();
    raycaster.setFromCamera(mouse, cameraRef.current);
    const intersects = raycaster.intersectObject(meshRef.current);

    if (intersects.length > 0) {
      const hit = intersects[0];
      const pt = hit.point;
      const uv = hit.uv;

      if (transectPointsRef.current.length >= 2) {
        clearTransect();
      }

      // 3D Point marker sphere
      const sphereGeo = new THREE.SphereGeometry(2.5, 16, 16);
      const isStart = transectPointsRef.current.length === 0;
      const sphereMat = new THREE.MeshBasicMaterial({ color: isStart ? 0x38bdf8 : 0xef4444 });
      const marker = new THREE.Mesh(sphereGeo, sphereMat);
      marker.position.copy(pt);
      sceneRef.current.add(marker);
      transectObjectsRef.current.push(marker);

      const newPts = [...transectPointsRef.current, { pt, uv }];
      transectPointsRef.current = newPts;

      if (newPts.length === 2) {
        // Connect points with 3D line
        const lineGeo = new THREE.BufferGeometry().setFromPoints([newPts[0].pt, newPts[1].pt]);
        const lineMat = new THREE.LineBasicMaterial({ color: 0x38bdf8, linewidth: 2 });
        const line = new THREE.Line(lineGeo, lineMat);
        sceneRef.current.add(line);
        transectObjectsRef.current.push(line);

        // Sample elevations along UV line
        const numSamples = 60;
        const gridW = meta.width;
        const gridH = meta.height;
        const elevs = rawElevationsRef.current || [];
        const sampledElevs = [];

        for (let i = 0; i < numSamples; i++) {
          const t = i / (numSamples - 1);
          const u = newPts[0].uv.x + t * (newPts[1].uv.x - newPts[0].uv.x);
          const v = newPts[0].uv.y + t * (newPts[1].uv.y - newPts[0].uv.y);

          const col = Math.max(0, Math.min(gridW - 1, Math.round(u * (gridW - 1))));
          const row = Math.max(0, Math.min(gridH - 1, Math.round((1.0 - v) * (gridH - 1))));
          const idx = row * gridW + col;
          sampledElevs.push(elevs[idx] !== undefined ? elevs[idx] : meta.min_elevation_m);
        }

        const deltaX_m = Math.abs(newPts[1].uv.x - newPts[0].uv.x) * (meta.cell_size_m ? meta.cell_size_m[0] * gridW : 30 * gridW);
        const deltaY_m = Math.abs(newPts[1].uv.y - newPts[0].uv.y) * (meta.cell_size_m ? meta.cell_size_m[1] * gridH : 30 * gridH);
        const distKm = Math.hypot(deltaX_m, deltaY_m) / 1000.0;

        let gain = 0, loss = 0;
        for (let i = 1; i < sampledElevs.length; i++) {
          const diff = sampledElevs[i] - sampledElevs[i - 1];
          if (diff > 0) gain += diff;
          else loss += Math.abs(diff);
        }

        setTransectResult({
          distance_km: distKm,
          elevations: sampledElevs,
          gain_m: gain,
          loss_m: loss,
          min_m: Math.min(...sampledElevs),
          max_m: Math.max(...sampledElevs),
        });
      }
    }
  };

  const resetView = () => {
    rotationRef.current = { x: 0.65, y: -0.75 };
    panRef.current = { x: 0, y: -20 };
    zoomRef.current = 260;
    if (cameraRef.current) {
      cameraRef.current.position.set(0, 160, 260);
      cameraRef.current.lookAt(0, 0, 0);
    }
    setExaggeration(1.8);
    setWireframe(false);
  };

  if (!isOpen) return null;

  return html`
    <div
      className="terrain-3d-modal-backdrop"
      style=${{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(3, 7, 18, 0.88)',
        backdropFilter: 'blur(6px)',
        zIndex: 9999,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '20px',
      }}
    >
      <div
        className="terrain-3d-container"
        style=${{
          position: 'relative',
          width: '100%',
          maxWidth: '1020px',
          background: '#0B1120',
          border: '1px solid #1E293B',
          borderRadius: '12px',
          boxShadow: '0 12px 40px rgba(0, 0, 0, 0.7)',
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <!-- Header Bar -->
        <div
          style=${{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '12px 18px',
            borderBottom: '1px solid #1E293B',
            background: '#0F172A',
          }}
        >
          <div style=${{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span style=${{ fontSize: '18px' }}>
              ${meta && (meta.is_lidar || (meta.source || '').toLowerCase().includes('lidar') || (meta.source || '').toLowerCase().includes('chm')) ? '🌲' : '🏔️'}
            </span>
            <div>
              <div style=${{ color: '#F8FAFC', fontWeight: 600, fontSize: '13.5px' }}>
                ${meta && (meta.is_lidar || (meta.source || '').toLowerCase().includes('lidar') || (meta.source || '').toLowerCase().includes('chm')) ? '3D LiDAR Canopy, Roads & Buildings Inspector' : title}
              </div>
              ${meta ? html`
                <div style=${{ color: '#94A3B8', fontSize: '11px', fontFamily: 'monospace' }}>
                  Source: ${meta.source} | ${meta.is_lidar || (meta.source || '').toLowerCase().includes('chm') ? 'Height Above Ground' : 'Elevation'}: ${meta.min_elevation_m}m to ${meta.max_elevation_m}m (Range: ${meta.elevation_range_m}m)
                </div>
              ` : null}
            </div>
          </div>
          <button
            onClick=${onClose}
            style=${{
              background: 'transparent',
              border: 'none',
              color: '#94A3B8',
              fontSize: '18px',
              cursor: 'pointer',
              padding: '4px 8px',
              borderRadius: '4px',
            }}
            title="Close 3D Viewer"
          >
            ✕
          </button>
        </div>

        <!-- 3D Canvas Mount Area -->
        <div
          style=${{
            position: 'relative',
            width: '100%',
            height: '480px',
            background: '#0B1120',
            cursor: measuring ? 'crosshair' : isDraggingRef.current ? 'grabbing' : 'grab',
          }}
          onMouseDown=${handleMouseDown}
          onMouseMove=${handleMouseMove}
          onMouseUp=${handleMouseUp}
          onWheel=${handleWheel}
          onContextMenu=${(e) => e.preventDefault()}
        >
          <div ref=${mountRef} style=${{ width: '100%', height: '100%' }} />

          ${loading && html`
            <div
              style=${{
                position: 'absolute',
                inset: 0,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '12px',
                color: '#38BDF8',
                background: 'rgba(11, 17, 32, 0.9)',
              }}
            >
              <div style=${{ fontSize: '24px', animation: 'spin 1s linear infinite' }}>⏳</div>
              <span style=${{ fontSize: '12.5px', fontFamily: 'monospace' }}>Constructing 3D Elevation Mesh...</span>
            </div>
          `}

          ${error && html`
            <div
              style=${{
                position: 'absolute',
                inset: 0,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#EF4444',
                padding: '20px',
                textAlign: 'center',
              }}
            >
              <span style=${{ fontSize: '20px', marginBottom: '8px' }}>⚠️</span>
              <span style=${{ fontSize: '13px' }}>${error}</span>
            </div>
          `}

          <div
            style=${{
              position: 'absolute',
              bottom: '12px',
              left: '14px',
              background: 'rgba(15, 23, 42, 0.75)',
              border: '1px solid rgba(51, 65, 85, 0.6)',
              padding: '6px 10px',
              borderRadius: '6px',
              color: '#94A3B8',
              fontSize: '10.5px',
              fontFamily: 'monospace',
              pointerEvents: 'none',
            }}
          >
            ${measuring
              ? '📍 TRANSECT MODE: Click Point A, then Point B on the 3D surface'
              : '🖱️ Left Drag: Rotate | Right Drag: Pan | Scroll: Zoom'}
          </div>
        </div>

        <!-- Real-Time Transect Profile Drawer (if measured) -->
        ${transectResult ? html`
          <div
            style=${{
              background: '#030712',
              borderTop: '1px solid #1E293B',
              padding: '10px 18px',
              fontSize: '11px',
              fontFamily: 'monospace',
              color: '#94A3B8',
            }}
          >
            <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
              <div style=${{ display: 'flex', alignItems: 'center', gap: '14px' }}>
                <span style=${{ color: '#38BDF8', fontWeight: 600 }}>📍 3D Slice Cross-Section:</span>
                <span>Dist: <b style=${{ color: '#F8FAFC' }}>${transectResult.distance_km.toFixed(2)} km</b></span>
                <span>Elev: <b style=${{ color: '#F8FAFC' }}>${transectResult.min_m.toFixed(0)}m – ${transectResult.max_m.toFixed(0)}m</b></span>
                <span>Gain: <b style=${{ color: '#10B981' }}>+${transectResult.gain_m.toFixed(0)}m</b></span>
                <span>Loss: <b style=${{ color: '#EF4444' }}>-${transectResult.loss_m.toFixed(0)}m</b></span>
              </div>
              <button
                onClick=${clearTransect}
                style=${{
                  background: 'transparent',
                  border: '1px solid #334155',
                  color: '#94A3B8',
                  padding: '2px 6px',
                  borderRadius: '4px',
                  cursor: 'pointer',
                  fontSize: '10px',
                }}
              >
                Clear Line
              </button>
            </div>
            <!-- Synced SVG Profile Mini-Graph -->
            <svg viewBox="0 0 700 45" style=${{ width: '100%', height: '45px', display: 'block' }}>
              ${(() => {
                const elevs = transectResult.elevations;
                const minE = transectResult.min_m;
                const maxE = transectResult.max_m;
                const range = Math.max(maxE - minE, 1.0);
                const pts = elevs.map((e, idx) => {
                  const x = (idx / (elevs.length - 1)) * 690 + 5;
                  const y = 40 - ((e - minE) / range) * 35;
                  return `${x.toFixed(1)},${y.toFixed(1)}`;
                }).join(' ');
                const area = `5,42 ${pts} 695,42`;
                return html`
                  <polygon points=${area} fill="#0284C7" fillOpacity="0.25" />
                  <polyline fill="none" stroke="#38BDF8" strokeWidth="2" strokeLinecap="round" points=${pts} />
                `;
              })()}
            </svg>
          </div>
        ` : null}

        <!-- Interactive Toolbar & Controls -->
        <div
          style=${{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '10px 18px',
            background: '#0F172A',
            borderTop: '1px solid #1E293B',
            fontSize: '12px',
            color: '#E2E8F0',
            flexWrap: 'wrap',
            gap: '10px',
          }}
        >
          <!-- Surface Style / Drape Selector -->
          <div style=${{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style=${{ color: '#94A3B8', fontWeight: 500 }}>Surface Layer:</span>
            <select
              value=${surfaceMode}
              onChange=${(e) => setSurfaceMode(e.target.value)}
              style=${{
                background: '#1E293B',
                color: '#F1F5F9',
                border: '1px solid #334155',
                borderRadius: '5px',
                padding: '4px 8px',
                fontSize: '11.5px',
                cursor: 'pointer',
              }}
            >
              ${meta && meta.orthophoto_url ? html`
                <option value=${meta.orthophoto_url}>📸 True-Color Aerial Photo (Real Roads & Buildings)</option>
              ` : null}
              <option value="realistic_urban">🏙️ Photorealistic Urban (Asphalt Roads, Buildings & Foliage)</option>
              <option value="lidar_canopy">🌲 LiDAR Canopy, Roads & Buildings (CHM)</option>
              <option value="lidar_discrete">🏷️ LiDAR Discrete Objects (Ground / Trees / Roofs)</option>
              <option value="desert">🏜️ Desert Sand & Mountain Crags</option>
              <option value="topographic">🏔️ Topographic Relief (Green to Snow)</option>
              <option value="urban">🏙️ Urban & Roads (Structural Contrast)</option>
              ${availableTextures.map((art) => {
                const name = typeof art === 'string' ? art : art.name || 'image.png';
                const url = typeof art === 'string' ? null : art.url;
                const baseName = name.split(/[/\\]/).pop();
                const isTif = baseName.toLowerCase().endsWith('.tif');
                const finalUrl = url || (isTif ? `/api/raster/png?path=${encodeURIComponent(name)}` : `/runs/${name}`);
                return html`
                  <option key=${name} value=${finalUrl}>
                    🗺️ Drape: ${baseName}
                  </option>
                `;
              })}
            </select>
          </div>

          <!-- Exaggeration Slider -->
          <div style=${{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style=${{ color: '#94A3B8', fontWeight: 500 }}>Elevation Scale:</span>
            <input
              type="range"
              min="0.5"
              max="5.0"
              step="0.1"
              value=${exaggeration}
              onChange=${(e) => setExaggeration(parseFloat(e.target.value))}
              style=${{ width: '100px', cursor: 'pointer', accentColor: '#38BDF8' }}
            />
            <span style=${{ fontFamily: 'monospace', color: '#38BDF8', fontWeight: 600, minWidth: '32px' }}>
              ${exaggeration.toFixed(1)}x
            </span>
          </div>

          <!-- Actions -->
          <div style=${{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <!-- Solid vs Point Cloud Mode Toggle -->
            <div style=${{ display: 'flex', alignItems: 'center', background: '#1E293B', padding: '2px', borderRadius: '6px', border: '1px solid #334155' }}>
              <button
                type="button"
                onClick=${() => setRenderMode('surface')}
                style=${{
                  background: renderMode === 'surface' ? '#0284C7' : 'transparent',
                  color: renderMode === 'surface' ? '#FFFFFF' : '#94A3B8',
                  border: 'none',
                  borderRadius: '4px',
                  padding: '3px 8px',
                  fontSize: '11px',
                  fontWeight: 500,
                  cursor: 'pointer',
                }}
                title="Continuous 3D Mesh Surface"
              >
                🌐 Surface
              </button>
              <button
                type="button"
                onClick=${() => setRenderMode('points')}
                style=${{
                  background: renderMode === 'points' ? '#0284C7' : 'transparent',
                  color: renderMode === 'points' ? '#FFFFFF' : '#94A3B8',
                  border: 'none',
                  borderRadius: '4px',
                  padding: '3px 8px',
                  fontSize: '11px',
                  fontWeight: 500,
                  cursor: 'pointer',
                }}
                title="Discrete LiDAR 3D Point Cloud returns"
              >
                ✨ Point Cloud
              </button>
            </div>

            <button
              onClick=${() => {
                setMeasuring(!measuring);
                if (measuring) clearTransect();
              }}
              style=${{
                background: measuring ? '#0284C7' : '#1E293B',
                color: measuring ? '#FFFFFF' : '#CBD5E1',
                border: '1px solid #334155',
                padding: '4px 10px',
                borderRadius: '5px',
                cursor: 'pointer',
                fontSize: '11.5px',
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
              }}
              title="Click two points on the 3D surface to slice an elevation profile"
            >
              <span>📍</span>
              <span>${measuring ? 'Measuring (Click 3D)' : 'Slice Profile'}</span>
            </button>

            <button
              onClick=${() => setWireframe(!wireframe)}
              style=${{
                background: wireframe ? '#0284C7' : '#1E293B',
                color: wireframe ? '#FFFFFF' : '#CBD5E1',
                border: '1px solid #334155',
                padding: '4px 10px',
                borderRadius: '5px',
                cursor: 'pointer',
                fontSize: '11.5px',
              }}
            >
              ${wireframe ? 'Solid Surface' : 'Wireframe'}
            </button>

            <button
              onClick=${resetView}
              style=${{
                background: '#1E293B',
                color: '#CBD5E1',
                border: '1px solid #334155',
                padding: '4px 10px',
                borderRadius: '5px',
                cursor: 'pointer',
                fontSize: '11.5px',
              }}
            >
              Reset
            </button>
          </div>
        </div>
      </div>
    </div>
  `;
}
