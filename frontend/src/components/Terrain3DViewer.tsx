import React, { useState, useEffect, useRef } from 'react';
import * as THREE from 'three';
import { Terrain3DPayload } from '@/types/geospatial';
import { ArtifactItem } from '@/types/sse';
import {
  Mountain,
  Trees,
  X,
  Loader2,
  AlertTriangle,
  MapPin,
  Globe,
  Sparkles,
  RotateCcw,
} from 'lucide-react';

export interface Terrain3DViewerProps {
  isOpen: boolean;
  onClose: () => void;
  payloadUrl: string;
  availableTextures?: Array<string | ArtifactItem>;
  title?: string;
}

interface TransectSamplePoint {
  pt: THREE.Vector3;
  uv: THREE.Vector2;
}

interface TransectResult {
  distance_km: number;
  elevations: number[];
  gain_m: number;
  loss_m: number;
  min_m: number;
  max_m: number;
}

const BUILTIN_THEMES = [
  'realistic_urban',
  'lidar_canopy',
  'lidar_discrete',
  'desert',
  'topographic',
  'urban',
];

export const Terrain3DViewer: React.FC<Terrain3DViewerProps> = ({
  isOpen,
  onClose,
  payloadUrl,
  availableTextures = [],
  title = '3D Digital Elevation Model',
}) => {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [meta, setMeta] = useState<Terrain3DPayload | null>(null);
  const [exaggeration, setExaggeration] = useState<number>(1.8);
  const [wireframe, setWireframe] = useState<boolean>(false);
  const [surfaceMode, setSurfaceMode] = useState<string>('desert');
  const [renderMode, setRenderMode] = useState<'surface' | 'points'>('surface');
  const [measuring, setMeasuring] = useState<boolean>(false);
  const [transectResult, setTransectResult] = useState<TransectResult | null>(null);

  // References to Three.js objects
  const sceneRef = useRef<THREE.Scene | null>(null);
  const meshRef = useRef<THREE.Mesh<THREE.PlaneGeometry, THREE.MeshLambertMaterial> | null>(null);
  const pointsRef = useRef<THREE.Points<THREE.PlaneGeometry, THREE.PointsMaterial> | null>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const animFrameRef = useRef<number | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const rawElevationsRef = useRef<number[] | null>(null);

  // Interaction state
  const isDraggingRef = useRef(false);
  const isRightDragRef = useRef(false);
  const clickStartPosRef = useRef({ x: 0, y: 0 });
  const prevMouseRef = useRef({ x: 0, y: 0 });
  const rotationRef = useRef({ x: 0.65, y: -0.75 });
  const panRef = useRef({ x: 0, y: -20 });
  const zoomRef = useRef(260);

  // Transect raycasting refs
  const transectPointsRef = useRef<TransectSamplePoint[]>([]);
  const transectObjectsRef = useRef<THREE.Object3D[]>([]);

  const clearTransect = () => {
    transectPointsRef.current = [];
    setTransectResult(null);
    if (sceneRef.current && transectObjectsRef.current.length > 0) {
      transectObjectsRef.current.forEach((obj) => sceneRef.current?.remove(obj));
      transectObjectsRef.current = [];
    }
  };

  const cleanupThree = () => {
    if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    clearTransect();
    if (rendererRef.current && rendererRef.current.domElement) {
      const parent = rendererRef.current.domElement.parentNode;
      if (parent) parent.removeChild(rendererRef.current.domElement);
      rendererRef.current.dispose();
    }
    if (meshRef.current) {
      meshRef.current.geometry?.dispose();
      if (meshRef.current.material) {
        meshRef.current.material.map?.dispose();
        meshRef.current.material.dispose();
      }
    }
    if (pointsRef.current) {
      pointsRef.current.material?.dispose();
      pointsRef.current = null;
    }
    sceneRef.current = null;
    meshRef.current = null;
    rendererRef.current = null;
  };

  const updateElevationVertices = (exagg: number, payloadData?: Terrain3DPayload | null) => {
    const mesh = meshRef.current;
    const elevs = rawElevationsRef.current;
    const activeMeta = payloadData || meta;
    if (!mesh || !elevs || !activeMeta) return;

    const pos = mesh.geometry.attributes.position;
    const isLidar = Boolean(
      activeMeta.is_lidar ||
        (activeMeta.source || '').toLowerCase().includes('lidar') ||
        (activeMeta.source || '').toLowerCase().includes('chm')
    );
    const minZ = activeMeta.min_elevation_m;
    const effectiveMinZ = isLidar ? Math.max(0.0, minZ) : Math.max(-500.0, minZ);

    let rangeZ = activeMeta.elevation_range_m;
    if (rangeZ > 5000.0 && isLidar) {
      rangeZ = 60.0;
    } else {
      rangeZ = Math.max(rangeZ, 1.0);
    }
    const zScale = (45.0 / rangeZ) * exagg;

    for (let i = 0; i < elevs.length; i++) {
      const e = elevs[i];
      const validElev = e < -500.0 || (isLidar && e < 0.0) ? effectiveMinZ : e;
      const zVal = Math.max(0.0, (validElev - effectiveMinZ) * zScale);
      pos.setZ(i, zVal);
    }
    pos.needsUpdate = true;
    mesh.geometry.computeVertexNormals();
  };

  const computeColorsForTheme = (themeName: string, data: Terrain3DPayload): Float32Array => {
    const isLidar = Boolean(
      data.is_lidar ||
        (data.source || '').toLowerCase().includes('lidar') ||
        (data.source || '').toLowerCase().includes('chm') ||
        data.elevation_range_m < 90
    );
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
      const safeElev = e < -500.0 || (isLidar && e < 0.0) ? effectiveMinZ : e;
      const normZ = Math.max(0, Math.min(1, (safeElev - effectiveMinZ) / rangeZ));
      const hs = (hillshade[i] !== undefined ? hillshade[i] : 180) / 255.0;

      let r = 0,
        g = 0,
        b = 0;

      if (themeName === 'realistic_urban') {
        const hM = isLidar ? Math.max(0.0, safeElev - effectiveMinZ) : normZ * 58.0;
        const shade = 0.25 + 0.75 * hs;

        if (hM < 0.5) {
          r = 0.18;
          g = 0.2;
          b = 0.23;
        } else if (hM < 1.5) {
          r = 0.36;
          g = 0.33;
          b = 0.28;
        } else if (hM < 3.0) {
          r = 0.24 + hs * 0.06;
          g = 0.52 + hs * 0.12;
          b = 0.18 + hs * 0.04;
        } else if (hM < 7.0) {
          const t = (hM - 3.0) / 4.0;
          r = 0.58 + t * 0.1;
          g = 0.52 + t * 0.04;
          b = 0.42 - t * 0.08;
        } else if (hM < 14.0) {
          const t = (hM - 7.0) / 7.0;
          r = 0.1 + t * 0.04;
          g = 0.44 - t * 0.08;
          b = 0.14 - t * 0.03;
        } else if (hM < 22.0) {
          const t = (hM - 14.0) / 8.0;
          r = 0.52 + t * 0.12;
          g = 0.54 + t * 0.1;
          b = 0.6 + t * 0.08;
        } else if (hM < 35.0) {
          const t = (hM - 22.0) / 13.0;
          r = 0.8 + t * 0.08;
          g = 0.38 - t * 0.06;
          b = 0.14 - t * 0.04;
        } else {
          r = 0.78;
          g = 0.74;
          b = 0.7;
        }
        r *= shade;
        g *= shade;
        b *= shade;
      } else if (themeName === 'lidar_canopy') {
        const hM = isLidar ? elevs[i] - minZ : normZ * 58.0;
        const shade = 0.28 + 0.72 * hs;

        if (hM < 0.5) {
          r = 0.18;
          g = 0.22;
          b = 0.26;
        } else if (hM < 1.2) {
          r = 0.48;
          g = 0.4;
          b = 0.3;
        } else if (hM < 2.8) {
          r = 0.38;
          g = 0.72;
          b = 0.18;
        } else if (hM < 6.0) {
          r = 0.14;
          g = 0.58;
          b = 0.22;
        } else if (hM < 14.0) {
          const t = (hM - 6.0) / 8.0;
          r = 0.08 + t * 0.02;
          g = 0.46 - t * 0.08;
          b = 0.18 - t * 0.04;
        } else if (hM < 22.0) {
          r = 0.06;
          g = 0.32;
          b = 0.12;
        } else if (hM < 35.0) {
          const t = (hM - 22.0) / 13.0;
          r = 0.78 + t * 0.1;
          g = 0.6 + t * 0.04;
          b = 0.32 - t * 0.08;
        } else {
          r = 0.9;
          g = 0.42;
          b = 0.1;
        }
        r *= shade;
        g *= shade;
        b *= shade;
      } else if (themeName === 'lidar_discrete') {
        const hM = isLidar ? elevs[i] - minZ : normZ * 58.0;
        const shade = 0.3 + 0.7 * hs;
        if (hM < 1.0) {
          r = 0.22;
          g = 0.28;
          b = 0.35;
        } else if (hM < 22.0) {
          r = 0.04;
          g = 0.7;
          b = 0.46;
        } else {
          r = 0.96;
          g = 0.62;
          b = 0.06;
        }
        r *= shade;
        g *= shade;
        b *= shade;
      } else if (themeName === 'desert') {
        if (normZ < 0.25) {
          const t = normZ / 0.25;
          r = 0.92 - t * 0.08;
          g = 0.76 - t * 0.14;
          b = 0.48 - t * 0.2;
        } else if (normZ < 0.65) {
          const t = (normZ - 0.25) / 0.4;
          r = 0.84 - t * 0.24;
          g = 0.62 - t * 0.24;
          b = 0.28 - t * 0.1;
        } else {
          const t = (normZ - 0.65) / 0.35;
          r = 0.6 - t * 0.25;
          g = 0.38 - t * 0.16;
          b = 0.18 + t * 0.04;
        }
      } else if (themeName === 'urban') {
        if (normZ < 0.3) {
          const t = normZ / 0.3;
          r = 0.35 + t * 0.15;
          g = 0.4 + t * 0.15;
          b = 0.45 + t * 0.15;
        } else {
          const t = (normZ - 0.3) / 0.7;
          r = 0.5 + t * 0.25;
          g = 0.55 + t * 0.2;
          b = 0.6 + t * 0.15;
        }
      } else {
        // Standard Topographic
        if (normZ < 0.2) {
          const t = normZ / 0.2;
          r = 0.15 + t * 0.25;
          g = 0.5 + t * 0.15;
          b = 0.25 - t * 0.1;
        } else if (normZ < 0.55) {
          const t = (normZ - 0.2) / 0.35;
          r = 0.4 + t * 0.32;
          g = 0.65 + t * 0.05;
          b = 0.15 + t * 0.15;
        } else if (normZ < 0.85) {
          const t = (normZ - 0.55) / 0.3;
          r = 0.72 - t * 0.2;
          g = 0.7 - t * 0.32;
          b = 0.3 - t * 0.05;
        } else {
          const t = (normZ - 0.85) / 0.15;
          r = 0.52 + t * 0.43;
          g = 0.38 + t * 0.57;
          b = 0.25 + t * 0.7;
        }
      }

      const shadeFactor = 0.35 + 0.65 * hs;
      colors[i * 3 + 0] = Math.min(1.0, r * shadeFactor);
      colors[i * 3 + 1] = Math.min(1.0, g * shadeFactor);
      colors[i * 3 + 2] = Math.min(1.0, b * shadeFactor);
    }
    return colors;
  };

  const applySurfaceMode = (mode: string, payloadData?: Terrain3DPayload | null) => {
    const mesh = meshRef.current;
    const activeMeta = payloadData || meta;
    if (!mesh || !activeMeta) return;

    if (BUILTIN_THEMES.includes(mode)) {
      const colors = computeColorsForTheme(mode, activeMeta);
      mesh.geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
      mesh.geometry.attributes.color.needsUpdate = true;
      if (mesh.material.map) {
        mesh.material.map.dispose();
        mesh.material.map = null;
      }
      mesh.material = new THREE.MeshLambertMaterial({
        vertexColors: true,
        side: THREE.DoubleSide,
        wireframe,
      });
      mesh.material.needsUpdate = true;
    } else {
      const loader = new THREE.TextureLoader();
      loader.load(mode, (tex) => {
        tex.colorSpace = THREE.SRGBColorSpace;
        if (!meshRef.current) return;
        meshRef.current.material = new THREE.MeshLambertMaterial({
          map: tex,
          side: THREE.DoubleSide,
          wireframe,
        });
        meshRef.current.material.needsUpdate = true;
      });
    }
  };

  const initThreeScene = (data: Terrain3DPayload, initialMode: string) => {
    const container = mountRef.current;
    if (!container) return;

    container.innerHTML = '';

    const width = container.clientWidth || 800;
    const height = container.clientHeight || 480;

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

    const ambientLight = new THREE.AmbientLight(0xd0e4ff, 0.45);
    scene.add(ambientLight);

    const dirLight = new THREE.DirectionalLight(0xfff5e0, 1.2);
    dirLight.position.set(-180, 320, 160);
    scene.add(dirLight);

    const fillLight = new THREE.DirectionalLight(0xaaccff, 0.35);
    fillLight.position.set(160, 100, -180);
    scene.add(fillLight);

    const gridW = data.width;
    const gridH = data.height;
    const meshSize = 200;

    const geometry = new THREE.PlaneGeometry(
      meshSize,
      meshSize * (gridH / gridW),
      gridW - 1,
      gridH - 1
    );
    const isBuiltInTheme = BUILTIN_THEMES.includes(initialMode);
    const colors = computeColorsForTheme(
      isBuiltInTheme ? initialMode : 'lidar_canopy',
      data
    );
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));

    const material = new THREE.MeshLambertMaterial({
      vertexColors: true,
      side: THREE.DoubleSide,
      wireframe,
    });

    const mesh = new THREE.Mesh(geometry, material);
    mesh.rotation.x = -Math.PI / 2;
    mesh.visible = renderMode === 'surface';
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
    points.visible = renderMode === 'points';
    scene.add(points);
    pointsRef.current = points;

    updateElevationVertices(exaggeration, data);

    if (initialMode && !isBuiltInTheme) {
      applySurfaceMode(initialMode, data);
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
      .then((data: Terrain3DPayload) => {
        if (!isMounted) return;
        setMeta(data);
        rawElevationsRef.current = data.elevations;
        const isLidar = Boolean(
          data.is_lidar ||
            (data.source || '').toLowerCase().includes('lidar') ||
            (data.source || '').toLowerCase().includes('chm')
        );
        const initialTheme = data.orthophoto_url
          ? data.orthophoto_url
          : isLidar
          ? 'realistic_urban'
          : data.default_surface || 'desert';
        setSurfaceMode(initialTheme);
        initThreeScene(data, initialTheme);
        setLoading(false);
      })
      .catch((err) => {
        if (isMounted) {
          setError(err instanceof Error ? err.message : String(err));
          setLoading(false);
        }
      });

    return () => {
      isMounted = false;
      cleanupThree();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, payloadUrl]);

  // Dynamic renderMode toggle (Solid Surface vs Point Cloud)
  useEffect(() => {
    if (meshRef.current) meshRef.current.visible = renderMode === 'surface';
    if (pointsRef.current) pointsRef.current.visible = renderMode === 'points';
  }, [renderMode]);

  // Dynamic exaggeration update without reconstructing the scene
  useEffect(() => {
    if (!meshRef.current || !rawElevationsRef.current || !meta) return;
    updateElevationVertices(exaggeration);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [exaggeration]);

  // Dynamic wireframe toggle
  useEffect(() => {
    if (meshRef.current && meshRef.current.material) {
      meshRef.current.material.wireframe = wireframe;
    }
  }, [wireframe]);

  // Surface mode change
  useEffect(() => {
    if (!meshRef.current || !meta) return;
    applySurfaceMode(surfaceMode);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [surfaceMode]);

  const handleMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    isDraggingRef.current = true;
    isRightDragRef.current = e.button === 2;
    clickStartPosRef.current = { x: e.clientX, y: e.clientY };
    prevMouseRef.current = { x: e.clientX, y: e.clientY };
  };

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!isDraggingRef.current) return;
    const dx = e.clientX - prevMouseRef.current.x;
    const dy = e.clientY - prevMouseRef.current.y;
    prevMouseRef.current = { x: e.clientX, y: e.clientY };

    if (isRightDragRef.current) {
      panRef.current.x += dx * 0.3;
      panRef.current.y -= dy * 0.3;
    } else {
      rotationRef.current.y += dx * 0.008;
      rotationRef.current.x = Math.max(
        -0.2,
        Math.min(1.4, rotationRef.current.x + dy * 0.008)
      );
    }
  };

  const handleMeshClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!meshRef.current || !cameraRef.current || !mountRef.current || !meta || !sceneRef.current) {
      return;
    }

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
      if (!uv) return;

      if (transectPointsRef.current.length >= 2) {
        clearTransect();
      }

      const sphereGeo = new THREE.SphereGeometry(2.5, 16, 16);
      const isStart = transectPointsRef.current.length === 0;
      const sphereMat = new THREE.MeshBasicMaterial({
        color: isStart ? 0x38bdf8 : 0xef4444,
      });
      const marker = new THREE.Mesh(sphereGeo, sphereMat);
      marker.position.copy(pt);
      sceneRef.current.add(marker);
      transectObjectsRef.current.push(marker);

      const newPts = [...transectPointsRef.current, { pt, uv }];
      transectPointsRef.current = newPts;

      if (newPts.length === 2) {
        const lineGeo = new THREE.BufferGeometry().setFromPoints([
          newPts[0].pt,
          newPts[1].pt,
        ]);
        const lineMat = new THREE.LineBasicMaterial({ color: 0x38bdf8, linewidth: 2 });
        const line = new THREE.Line(lineGeo, lineMat);
        sceneRef.current.add(line);
        transectObjectsRef.current.push(line);

        const numSamples = 60;
        const gridW = meta.width;
        const gridH = meta.height;
        const elevs = rawElevationsRef.current || [];
        const sampledElevs: number[] = [];

        for (let i = 0; i < numSamples; i++) {
          const t = i / (numSamples - 1);
          const u = newPts[0].uv.x + t * (newPts[1].uv.x - newPts[0].uv.x);
          const v = newPts[0].uv.y + t * (newPts[1].uv.y - newPts[0].uv.y);

          const col = Math.max(0, Math.min(gridW - 1, Math.round(u * (gridW - 1))));
          const row = Math.max(0, Math.min(gridH - 1, Math.round((1.0 - v) * (gridH - 1))));
          const idx = row * gridW + col;
          sampledElevs.push(elevs[idx] !== undefined ? elevs[idx] : meta.min_elevation_m);
        }

        const cellX = meta.cell_size_m ? meta.cell_size_m[0] : 30;
        const cellY = meta.cell_size_m ? meta.cell_size_m[1] : 30;
        const deltaX_m = Math.abs(newPts[1].uv.x - newPts[0].uv.x) * cellX * gridW;
        const deltaY_m = Math.abs(newPts[1].uv.y - newPts[0].uv.y) * cellY * gridH;
        const distKm = Math.hypot(deltaX_m, deltaY_m) / 1000.0;

        let gain = 0,
          loss = 0;
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

  const handleMouseUp = (e: React.MouseEvent<HTMLDivElement>) => {
    isDraggingRef.current = false;
    const distMoved = Math.hypot(
      e.clientX - clickStartPosRef.current.x,
      e.clientY - clickStartPosRef.current.y
    );
    if (distMoved < 5 && measuring) {
      handleMeshClick(e);
    }
  };

  const handleWheel = (e: React.WheelEvent<HTMLDivElement>) => {
    zoomRef.current = Math.max(80, Math.min(600, zoomRef.current + e.deltaY * 0.35));
    if (cameraRef.current) {
      cameraRef.current.position.z = zoomRef.current;
      cameraRef.current.position.y = zoomRef.current * 0.65;
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

  const isLidarModel = Boolean(
    meta &&
      (meta.is_lidar ||
        (meta.source || '').toLowerCase().includes('lidar') ||
        (meta.source || '').toLowerCase().includes('chm'))
  );

  return (
    <div className="fixed inset-0 z-[1300] bg-slate-950/90 backdrop-blur-md flex items-center justify-center p-5">
      <div className="relative w-full max-w-[1020px] bg-muted border border-border rounded-none shadow-2xl overflow-hidden flex flex-col">
        {/* Header Bar */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-border bg-card">
          <div className="flex items-center gap-2.5">
            {isLidarModel ? (
              <Trees className="h-5 w-5 text-emerald-400" />
            ) : (
              <Mountain className="h-5 w-5 text-sky-400" />
            )}
            <div>
              <div className="text-foreground font-semibold text-sm">
                {isLidarModel ? '3D LiDAR Canopy, Roads & Buildings Inspector' : title}
              </div>
              {meta && (
                <div className="text-muted-foreground text-[11px] font-mono">
                  Source: {meta.source || 'Raster'} |{' '}
                  {isLidarModel ? 'Height Above Ground' : 'Elevation'}: {meta.min_elevation_m}m to{' '}
                  {meta.max_elevation_m}m (Range: {meta.elevation_range_m}m)
                </div>
              )}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            title="Close 3D Viewer"
            className="p-1.5 rounded-none text-muted-foreground hover:text-white hover:bg-slate-800 transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* 3D Canvas Mount Area */}
        <div
          style={{
            cursor: measuring ? 'crosshair' : isDraggingRef.current ? 'grabbing' : 'grab',
          }}
          className="relative w-full h-[480px] bg-muted"
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onWheel={handleWheel}
          onContextMenu={(e) => e.preventDefault()}
        >
          <div ref={mountRef} className="w-full h-full" />

          {loading && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-sky-400 bg-muted/90">
              <Loader2 className="h-7 w-7 animate-spin" />
              <span className="text-xs font-mono">Constructing 3D Elevation Mesh...</span>
            </div>
          )}

          {error && (
            <div className="absolute inset-0 flex flex-col items-center justify-center text-rose-400 p-6 text-center gap-2">
              <AlertTriangle className="h-6 w-6" />
              <span className="text-xs font-mono">{error}</span>
            </div>
          )}

          <div className="absolute bottom-3 left-3.5 bg-slate-900/80 border border-slate-700/60 px-2.5 py-1.5 rounded-none text-muted-foreground text-[10.5px] font-mono pointer-events-none">
            {measuring
              ? '📍 TRANSECT MODE: Click Point A, then Point B on the 3D surface'
              : '🖱️ Left Drag: Rotate | Right Drag: Pan | Scroll: Zoom'}
          </div>
        </div>

        {/* Real-Time Transect Profile Drawer (if measured) */}
        {transectResult && (
          <div className="bg-[#030712] border-t border-border px-4 py-2.5 text-[11px] font-mono text-muted-foreground">
            <div className="flex items-center justify-between mb-1.5">
              <div className="flex items-center gap-3.5 flex-wrap">
                <span className="text-sky-400 font-semibold">📍 3D Slice Cross-Section:</span>
                <span>
                  Dist: <b className="text-foreground">{transectResult.distance_km.toFixed(2)} km</b>
                </span>
                <span>
                  Elev:{' '}
                  <b className="text-foreground">
                    {transectResult.min_m.toFixed(0)}m – {transectResult.max_m.toFixed(0)}m
                  </b>
                </span>
                <span>
                  Gain: <b className="text-emerald-400">+{transectResult.gain_m.toFixed(0)}m</b>
                </span>
                <span>
                  Loss: <b className="text-rose-400">-{transectResult.loss_m.toFixed(0)}m</b>
                </span>
              </div>
              <button
                type="button"
                onClick={clearTransect}
                className="border border-slate-700 text-muted-foreground hover:text-white px-2 py-0.5 rounded-none text-[10px]"
              >
                Clear Line
              </button>
            </div>
            <svg viewBox="0 0 700 45" className="w-full h-[45px] block">
              {(() => {
                const elevs = transectResult.elevations;
                const minE = transectResult.min_m;
                const maxE = transectResult.max_m;
                const range = Math.max(maxE - minE, 1.0);
                const pts = elevs
                  .map((e, idx) => {
                    const x = (idx / (elevs.length - 1)) * 690 + 5;
                    const y = 40 - ((e - minE) / range) * 35;
                    return `${x.toFixed(1)},${y.toFixed(1)}`;
                  })
                  .join(' ');
                const area = `5,42 ${pts} 695,42`;
                return (
                  <>
                    <polygon points={area} fill="#0284C7" fillOpacity="0.25" />
                    <polyline
                      fill="none"
                      stroke="#38BDF8"
                      strokeWidth="2"
                      strokeLinecap="round"
                      points={pts}
                    />
                  </>
                );
              })()}
            </svg>
          </div>
        )}

        {/* Interactive Toolbar & Controls */}
        <div className="flex items-center justify-between px-4 py-2.5 bg-card border-t border-border text-xs text-foreground flex-wrap gap-2.5">
          {/* Surface Style / Drape Selector */}
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground font-medium">Surface Layer:</span>
            <select
              value={surfaceMode}
              onChange={(e) => setSurfaceMode(e.target.value)}
              className="bg-muted text-foreground border border-slate-700 rounded-none px-2 py-1 text-[11.5px] cursor-pointer outline-none"
            >
              {meta?.orthophoto_url && (
                <option value={meta.orthophoto_url}>
                  📸 True-Color Aerial Photo (Real Roads & Buildings)
                </option>
              )}
              <option value="realistic_urban">
                🏙️ Photorealistic Urban (Asphalt Roads, Buildings & Foliage)
              </option>
              <option value="lidar_canopy">🌲 LiDAR Canopy, Roads & Buildings (CHM)</option>
              <option value="lidar_discrete">
                🏷️ LiDAR Discrete Objects (Ground / Trees / Roofs)
              </option>
              <option value="desert">🏜️ Desert Sand & Mountain Crags</option>
              <option value="topographic">🏔️ Topographic Relief (Green to Snow)</option>
              <option value="urban">🏙️ Urban & Roads (Structural Contrast)</option>
              {availableTextures.map((art) => {
                const name = typeof art === 'string' ? art : art.name || 'image.png';
                const url = typeof art === 'string' ? null : art.url || art.path;
                const baseName = name.replace(/\\/g, '/').split('/').pop() || name;
                const isTif = baseName.toLowerCase().endsWith('.tif');
                const finalUrl =
                  url ||
                  (isTif
                    ? `/api/raster/png?path=${encodeURIComponent(name)}`
                    : `/runs/${name}`);
                return (
                  <option key={name} value={finalUrl}>
                    🗺️ Drape: {baseName}
                  </option>
                );
              })}
            </select>
          </div>

          {/* Exaggeration Slider */}
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground font-medium">Elevation Scale:</span>
            <input
              type="range"
              min={0.5}
              max={5.0}
              step={0.1}
              value={exaggeration}
              onChange={(e) => setExaggeration(parseFloat(e.target.value))}
              className="w-[100px] cursor-pointer accent-sky-400"
            />
            <span className="font-mono text-sky-400 font-semibold min-w-[32px]">
              {exaggeration.toFixed(1)}x
            </span>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-2">
            {/* Solid vs Point Cloud Mode Toggle */}
            <div className="flex items-center bg-muted p-0.5 rounded-none border border-slate-700">
              <button
                type="button"
                onClick={() => setRenderMode('surface')}
                title="Continuous 3D Mesh Surface"
                className={`inline-flex items-center gap-1 rounded-none px-2 py-1 text-[11px] font-medium transition-colors ${
                  renderMode === 'surface'
                    ? 'bg-sky-600 text-white'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                <Globe className="h-3 w-3" />
                Surface
              </button>
              <button
                type="button"
                onClick={() => setRenderMode('points')}
                title="Discrete LiDAR 3D Point Cloud returns"
                className={`inline-flex items-center gap-1 rounded-none px-2 py-1 text-[11px] font-medium transition-colors ${
                  renderMode === 'points'
                    ? 'bg-sky-600 text-white'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                <Sparkles className="h-3 w-3" />
                Point Cloud
              </button>
            </div>

            <button
              type="button"
              onClick={() => {
                setMeasuring((prev) => {
                  const next = !prev;
                  if (!next) clearTransect();
                  return next;
                });
              }}
              title="Click two points on the 3D surface to slice an elevation profile"
              className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-none border border-slate-700 text-[11.5px] transition-colors ${
                measuring
                  ? 'bg-sky-600 text-white'
                  : 'bg-muted text-foreground hover:text-white'
              }`}
            >
              <MapPin className="h-3 w-3" />
              <span>{measuring ? 'Measuring (Click 3D)' : 'Slice Profile'}</span>
            </button>

            <button
              type="button"
              onClick={() => setWireframe((prev) => !prev)}
              className={`px-2.5 py-1 rounded-none border border-slate-700 text-[11.5px] transition-colors ${
                wireframe
                  ? 'bg-sky-600 text-white'
                  : 'bg-muted text-foreground hover:text-white'
              }`}
            >
              {wireframe ? 'Solid Surface' : 'Wireframe'}
            </button>

            <button
              type="button"
              onClick={resetView}
              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-none bg-muted border border-slate-700 text-foreground hover:text-white text-[11.5px] transition-colors"
            >
              <RotateCcw className="h-3 w-3" />
              Reset
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

