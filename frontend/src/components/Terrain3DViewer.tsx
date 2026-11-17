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

const MESH_SIZE = 200;

function checkIsLidar(data: Terrain3DPayload): boolean {
  return Boolean(
    data.is_lidar ||
      (data.source || '').toLowerCase().includes('lidar') ||
      (data.source || '').toLowerCase().includes('chm')
  );
}

function computeZScale(data: Terrain3DPayload, exagg: number): number {
  const isLidar = checkIsLidar(data);
  if (isLidar) {
    // True 1:1 metric proportion relative to the 200-unit horizontal mesh.
    // Prefer projected bounds width (immune to resampled cell_size_m in older payloads).
    const boundsWidth =
      Array.isArray(data.bounds) && data.bounds.length === 4
        ? Math.abs(data.bounds[2] - data.bounds[0])
        : 0;
    const isProjectedMeters = boundsWidth > 50 && !(data.crs || '').includes('4326');
    const cellX = data.cell_size_m?.[0] || 2.0;
    const sceneWidthM = isProjectedMeters ? boundsWidth : Math.max(data.width * cellX, 1.0);
    return (MESH_SIZE / sceneWidthM) * exagg;
  }
  const rangeZ = Math.max(data.elevation_range_m || 1.0, 1.0);
  return (45.0 / rangeZ) * exagg;
}

function createCirclePointSprite(): THREE.CanvasTexture | null {
  const canvas = document.createElement('canvas');
  canvas.width = 32;
  canvas.height = 32;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  const grad = ctx.createRadialGradient(16, 16, 2, 16, 16, 15);
  grad.addColorStop(0, 'rgba(255,255,255,1)');
  grad.addColorStop(0.7, 'rgba(255,255,255,0.92)');
  grad.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, 32, 32);
  const tex = new THREE.CanvasTexture(canvas);
  tex.needsUpdate = true;
  return tex;
}

/**
 * Builds a MeshStandardMaterial that keeps top-down surfaces (roofs, roads, fields, tree tops)
 * 100% photorealistic while gently shading steep vertical cliff faces (building walls / canopy sides)
 * so top-down pixels don't smear into muddy mountain slopes.
 */
function createDsmSurfaceMaterial(
  tex: THREE.Texture | null,
  wireframe: boolean,
  isLidar: boolean
): THREE.MeshStandardMaterial {
  const mat = new THREE.MeshStandardMaterial({
    map: tex,
    vertexColors: true,
    roughness: 0.86,
    metalness: 0.04,
    side: THREE.DoubleSide,
    wireframe,
  });

  if (tex && isLidar) {
    mat.onBeforeCompile = (shader) => {
      shader.vertexShader = shader.vertexShader
        .replace(
          '#include <common>',
          '#include <common>\nvarying float vUpSlope;'
        )
        .replace(
          '#include <beginnormal_vertex>',
          '#include <beginnormal_vertex>\nvUpSlope = clamp(objectNormal.y, 0.0, 1.0);'
        );

      shader.fragmentShader = shader.fragmentShader
        .replace(
          '#include <common>',
          '#include <common>\nvarying float vUpSlope;'
        )
        .replace(
          '#include <map_fragment>',
          `#include <map_fragment>
           // Blend steep vertical walls toward neutral shaded facade/understory tone
           float wallFactor = 1.0 - smoothstep(0.32, 0.68, vUpSlope);
           float luma = dot(diffuseColor.rgb, vec3(0.299, 0.587, 0.114));
           vec3 facadeTone = mix(vec3(luma * 0.65), diffuseColor.rgb * 0.52, 0.35);
           diffuseColor.rgb = mix(diffuseColor.rgb, facadeTone, wallFactor * 0.72);`
        );
    };
  }
  return mat;
}

function sampleImagePixels(
  url: string,
  targetW: number,
  targetH: number
): Promise<Uint8ClampedArray | null> {
  return new Promise((resolve) => {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => {
      try {
        const canvas = document.createElement('canvas');
        canvas.width = targetW;
        canvas.height = targetH;
        const ctx = canvas.getContext('2d');
        if (!ctx) {
          resolve(null);
          return;
        }
        ctx.drawImage(img, 0, 0, targetW, targetH);
        resolve(ctx.getImageData(0, 0, targetW, targetH).data);
      } catch {
        resolve(null);
      }
    };
    img.onerror = () => resolve(null);
    img.src = url;
  });
}

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
  const [exaggeration, setExaggeration] = useState<number>(1.0);
  const [wireframe, setWireframe] = useState<boolean>(false);
  const [surfaceMode, setSurfaceMode] = useState<string>('realistic_urban');
  const [renderMode, setRenderMode] = useState<'surface' | 'points'>('surface');
  const [measuring, setMeasuring] = useState<boolean>(false);
  const [transectResult, setTransectResult] = useState<TransectResult | null>(null);

  // Three.js object refs
  const sceneRef = useRef<THREE.Scene | null>(null);
  const worldGroupRef = useRef<THREE.Group | null>(null);
  const surfaceGroupRef = useRef<THREE.Group | null>(null);
  const meshRef = useRef<THREE.Mesh<THREE.PlaneGeometry, THREE.MeshStandardMaterial> | null>(null);
  const pointsRef = useRef<THREE.Points<THREE.BufferGeometry, THREE.PointsMaterial> | null>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const animFrameRef = useRef<number | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);

  // Cached data refs for instant exaggeration updates
  const rawElevationsRef = useRef<number[] | null>(null);
  const pointBaseHeightsRef = useRef<Float32Array | null>(null);

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
    if (worldGroupRef.current && transectObjectsRef.current.length > 0) {
      transectObjectsRef.current.forEach((obj) => worldGroupRef.current?.remove(obj));
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
      meshRef.current.material?.map?.dispose();
      meshRef.current.material?.dispose();
    }
    if (pointsRef.current) {
      pointsRef.current.geometry?.dispose();
      pointsRef.current.material?.map?.dispose();
      pointsRef.current.material?.dispose();
    }
    sceneRef.current = null;
    worldGroupRef.current = null;
    surfaceGroupRef.current = null;
    meshRef.current = null;
    pointsRef.current = null;
    rendererRef.current = null;
    pointBaseHeightsRef.current = null;
  };

  const updateElevationVertices = (exagg: number, payloadData?: Terrain3DPayload | null) => {
    const mesh = meshRef.current;
    const activeMeta = payloadData || meta;
    if (!mesh || !activeMeta) return;

    const isLidar = checkIsLidar(activeMeta);
    const zScale = computeZScale(activeMeta, exagg);
    const minZ = activeMeta.min_elevation_m;
    const effectiveMinZ = isLidar ? Math.max(0.0, minZ) : Math.max(-500.0, minZ);

    // 1. Update continuous DSM / terrain mesh vertices
    const elevSource = rawElevationsRef.current;
    if (elevSource) {
      const pos = mesh.geometry.attributes.position;
      for (let i = 0; i < elevSource.length; i++) {
        const e = elevSource[i];
        const validElev = e < -500.0 || (isLidar && e < 0.0) ? effectiveMinZ : e;
        const yVal = Math.max(0.0, (validElev - effectiveMinZ) * zScale);
        pos.setY(i, yVal);
      }
      pos.needsUpdate = true;
      mesh.geometry.computeVertexNormals();
    }

    // 2. Update Point Cloud heights
    if (pointsRef.current && pointBaseHeightsRef.current) {
      const pPos = pointsRef.current.geometry.attributes.position;
      const baseH = pointBaseHeightsRef.current;
      for (let i = 0; i < baseH.length; i++) {
        pPos.setY(i, Math.max(0, baseH[i] * zScale));
      }
      pPos.needsUpdate = true;
    }
  };

  /**
   * Computes subtle grayscale ambient occlusion from multi-directional hillshade
   * so photorealistic aerial textures retain crisp depth in crevices and under-canopy areas.
   */
  const computeAmbientOcclusionColors = (data: Terrain3DPayload): Float32Array => {
    const elevs = data.elevations;
    const hillshade = data.hillshade || [];
    const colors = new Float32Array(elevs.length * 3);
    for (let i = 0; i < elevs.length; i++) {
      const hs = (hillshade[i] !== undefined ? hillshade[i] : 200) / 255.0;
      const ao = Math.min(1.0, 0.72 + 0.30 * hs);
      colors[i * 3 + 0] = ao;
      colors[i * 3 + 1] = ao;
      colors[i * 3 + 2] = ao;
    }
    return colors;
  };

  const computeColorsForTheme = (themeName: string, data: Terrain3DPayload): Float32Array => {
    const isLidar = checkIsLidar(data) || data.elevation_range_m < 90;
    const minZ = data.min_elevation_m;
    const effectiveMinZ = isLidar ? Math.max(0.0, minZ) : Math.max(-500.0, minZ);
    const rangeZ = Math.max(isLidar && data.elevation_range_m > 5000 ? 60.0 : data.elevation_range_m, 1.0);

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

      if (themeName === 'realistic_urban' || themeName === 'lidar_canopy') {
        const hM = isLidar ? Math.max(0.0, safeElev - effectiveMinZ) : normZ * 58.0;
        if (hM < 0.5) {
          r = 0.2;
          g = 0.22;
          b = 0.24;
        } else if (hM < 2.0) {
          r = 0.34;
          g = 0.32;
          b = 0.26;
        } else if (hM < 12.0) {
          r = 0.16;
          g = 0.48;
          b = 0.2;
        } else if (hM < 24.0) {
          r = 0.12;
          g = 0.36;
          b = 0.16;
        } else {
          r = 0.65;
          g = 0.62;
          b = 0.58;
        }
      } else if (themeName === 'lidar_discrete') {
        const hM = isLidar ? Math.max(0.0, safeElev - effectiveMinZ) : normZ * 58.0;
        if (hM < 1.0) {
          r = 0.22;
          g = 0.26;
          b = 0.32;
        } else if (hM < 22.0) {
          r = 0.12;
          g = 0.62;
          b = 0.38;
        } else {
          r = 0.85;
          g = 0.58;
          b = 0.18;
        }
      } else if (themeName === 'desert') {
        r = 0.85 - normZ * 0.35;
        g = 0.68 - normZ * 0.32;
        b = 0.42 - normZ * 0.2;
      } else if (themeName === 'urban') {
        r = 0.35 + normZ * 0.38;
        g = 0.38 + normZ * 0.35;
        b = 0.42 + normZ * 0.32;
      } else {
        r = 0.2 + normZ * 0.55;
        g = 0.52 - normZ * 0.12;
        b = 0.22 + normZ * 0.4;
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
      mesh.material = new THREE.MeshStandardMaterial({
        vertexColors: true,
        roughness: 0.88,
        metalness: 0.04,
        side: THREE.DoubleSide,
        wireframe,
      });
      mesh.material.needsUpdate = true;
    } else {
      const loader = new THREE.TextureLoader();
      loader.load(mode, (tex) => {
        tex.colorSpace = THREE.SRGBColorSpace;
        tex.minFilter = THREE.LinearMipmapLinearFilter;
        tex.magFilter = THREE.LinearFilter;
        if (rendererRef.current) {
          tex.anisotropy = Math.min(8, rendererRef.current.capabilities.getMaxAnisotropy());
        }
        if (!meshRef.current) return;

        // Subtle ambient occlusion multiplied with photorealistic aerial texture
        const aoColors = computeAmbientOcclusionColors(activeMeta);
        meshRef.current.geometry.setAttribute('color', new THREE.BufferAttribute(aoColors, 3));
        meshRef.current.geometry.attributes.color.needsUpdate = true;

        if (meshRef.current.material.map) {
          meshRef.current.material.map.dispose();
        }
        meshRef.current.material.dispose();
        meshRef.current.material = createDsmSurfaceMaterial(
          tex,
          wireframe,
          checkIsLidar(activeMeta)
        );
        meshRef.current.material.needsUpdate = true;
      });
    }
  };

  const initThreeScene = async (data: Terrain3DPayload, initialMode: string, exagg: number) => {
    const container = mountRef.current;
    if (!container) return;

    container.innerHTML = '';

    const width = container.clientWidth || 800;
    const height = container.clientHeight || 480;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0b0f17);
    sceneRef.current = scene;

    const worldGroup = new THREE.Group();
    scene.add(worldGroup);
    worldGroupRef.current = worldGroup;

    const surfaceGroup = new THREE.Group();
    worldGroup.add(surfaceGroup);
    surfaceGroupRef.current = surfaceGroup;

    const camera = new THREE.PerspectiveCamera(40, width / height, 1, 3000);
    cameraRef.current = camera;

    const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2.0));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.08;
    container.appendChild(renderer.domElement);
    rendererRef.current = renderer;

    // Realistic outdoor sky/ground hemisphere + directional sun with crisp shadows
    const hemiLight = new THREE.HemisphereLight(0xe0f2fe, 0x334155, 0.72);
    scene.add(hemiLight);

    const dirLight = new THREE.DirectionalLight(0xfffbeb, 1.35);
    dirLight.position.set(-160, 260, 140);
    dirLight.castShadow = true;
    dirLight.shadow.mapSize.width = 2048;
    dirLight.shadow.mapSize.height = 2048;
    dirLight.shadow.camera.near = 40;
    dirLight.shadow.camera.far = 750;
    dirLight.shadow.camera.left = -140;
    dirLight.shadow.camera.right = 140;
    dirLight.shadow.camera.top = 140;
    dirLight.shadow.camera.bottom = -140;
    dirLight.shadow.bias = -0.0005;
    scene.add(dirLight);

    const fillLight = new THREE.DirectionalLight(0xbae6fd, 0.35);
    fillLight.position.set(160, 90, -160);
    scene.add(fillLight);

    const gridW = data.width;
    const gridH = data.height;
    const planeW = MESH_SIZE;
    const planeD = MESH_SIZE * (gridH / gridW);
    const isLidar = checkIsLidar(data);

    // Sample aerial orthophoto if available so Point Cloud mode has true photorealistic RGB
    const pixels = data.orthophoto_url
      ? await sampleImagePixels(data.orthophoto_url, gridW, gridH)
      : null;

    const elevs = data.elevations;

    // 1. High-Resolution Continuous Photorealistic DSM Mesh
    const geometry = new THREE.PlaneGeometry(planeW, planeD, gridW - 1, gridH - 1);
    geometry.rotateX(-Math.PI / 2);

    const isBuiltInTheme = BUILTIN_THEMES.includes(initialMode);
    const colors = isBuiltInTheme
      ? computeColorsForTheme(initialMode, data)
      : computeAmbientOcclusionColors(data);
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));

    const material = new THREE.MeshStandardMaterial({
      vertexColors: true,
      roughness: 0.88,
      metalness: 0.04,
      side: THREE.DoubleSide,
      wireframe,
    });

    const mesh = new THREE.Mesh(geometry, material);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    surfaceGroup.add(mesh);
    meshRef.current = mesh;

    // 2. Production-Grade Multi-Return 3D LiDAR Point Cloud
    const pointPositions: number[] = [];
    const pointColors: number[] = [];
    const pointHeights: number[] = [];
    const ptStride = gridW > 520 ? 2 : 1;
    const cellWorldW = planeW / Math.max(gridW - 1, 1);
    const cellWorldD = planeD / Math.max(gridH - 1, 1);

    for (let row = 0; row < gridH; row += ptStride) {
      for (let col = 0; col < gridW; col += ptStride) {
        const idx = row * gridW + col;
        const hM = isLidar
          ? Math.max(0, elevs[idx] - Math.max(0, data.min_elevation_m))
          : Math.max(0, elevs[idx] - Math.max(-500, data.min_elevation_m));

        // Deterministic subtle sub-cell jitter for authentic airborne LiDAR scan density
        const hash = Math.sin(col * 12.9898 + row * 78.233) * 43758.5453;
        const jx = ((hash - Math.floor(hash)) - 0.5) * cellWorldW * 0.45;
        const hash2 = Math.sin(row * 39.346 + col * 11.135) * 24634.6345;
        const jz = ((hash2 - Math.floor(hash2)) - 0.5) * cellWorldD * 0.45;

        const x = (col / Math.max(gridW - 1, 1) - 0.5) * planeW + jx;
        const z = (row / Math.max(gridH - 1, 1) - 0.5) * planeD + jz;

        const r = pixels ? pixels[idx * 4] / 255 : colors[idx * 3];
        const g = pixels ? pixels[idx * 4 + 1] / 255 : colors[idx * 3 + 1];
        const b = pixels ? pixels[idx * 4 + 2] / 255 : colors[idx * 3 + 2];

        pointPositions.push(x, 0, z);
        pointHeights.push(hM);
        pointColors.push(r, g, b);

        // Sub-canopy / facade intermediate laser returns for tall structures & trees
        if (isLidar && hM > 2.8) {
          pointPositions.push(x - jx * 0.6, 0, z - jz * 0.6);
          pointHeights.push(hM * 0.64);
          pointColors.push(r * 0.82, g * 0.82, b * 0.82);
        }
        if (isLidar && hM > 7.5) {
          pointPositions.push(x + jx * 0.5, 0, z + jz * 0.5);
          pointHeights.push(hM * 0.34);
          pointColors.push(r * 0.68, g * 0.68, b * 0.68);
        }
      }
    }

    const ptGeo = new THREE.BufferGeometry();
    ptGeo.setAttribute('position', new THREE.Float32BufferAttribute(pointPositions, 3));
    ptGeo.setAttribute('color', new THREE.Float32BufferAttribute(pointColors, 3));
    pointBaseHeightsRef.current = new Float32Array(pointHeights);

    const pointSprite = createCirclePointSprite();
    const ptMat = new THREE.PointsMaterial({
      size: 1.75,
      map: pointSprite,
      alphaTest: 0.35,
      transparent: true,
      vertexColors: true,
      sizeAttenuation: true,
    });
    const points = new THREE.Points(ptGeo, ptMat);
    points.visible = renderMode === 'points';
    worldGroup.add(points);
    pointsRef.current = points;

    surfaceGroup.visible = renderMode === 'surface';

    updateElevationVertices(exagg, data);

    if (initialMode && !isBuiltInTheme) {
      applySurfaceMode(initialMode, data);
    }

    camera.position.set(0, 140, zoomRef.current);
    camera.lookAt(0, 0, 0);

    const animate = () => {
      animFrameRef.current = requestAnimationFrame(animate);
      if (worldGroupRef.current) {
        worldGroupRef.current.rotation.x = rotationRef.current.x;
        worldGroupRef.current.rotation.y = rotationRef.current.y;
        worldGroupRef.current.position.x = panRef.current.x;
        worldGroupRef.current.position.y = panRef.current.y;
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
      .then(async (data: Terrain3DPayload) => {
        if (!isMounted) return;
        setMeta(data);
        rawElevationsRef.current = data.elevations;
        const isLidar = checkIsLidar(data);
        const defaultExagg = isLidar ? 1.0 : 1.8;
        setExaggeration(defaultExagg);
        const initialTheme = data.orthophoto_url
          ? data.orthophoto_url
          : isLidar
          ? 'realistic_urban'
          : data.default_surface || 'desert';
        setSurfaceMode(initialTheme);
        await initThreeScene(data, initialTheme, defaultExagg);
        if (isMounted) setLoading(false);
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

  // Dynamic renderMode toggle (3D City & Canopy Surface vs Point Cloud)
  useEffect(() => {
    if (surfaceGroupRef.current) surfaceGroupRef.current.visible = renderMode === 'surface';
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
        -0.1,
        Math.min(1.4, rotationRef.current.x + dy * 0.008)
      );
    }
  };

  const handleMeshClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!meshRef.current || !cameraRef.current || !mountRef.current || !meta || !worldGroupRef.current) {
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
      const localPt = worldGroupRef.current.worldToLocal(hit.point.clone());
      const uv = hit.uv;
      if (!uv) return;

      if (transectPointsRef.current.length >= 2) {
        clearTransect();
      }

      const sphereGeo = new THREE.SphereGeometry(2.2, 16, 16);
      const isStart = transectPointsRef.current.length === 0;
      const sphereMat = new THREE.MeshBasicMaterial({
        color: isStart ? 0x38bdf8 : 0xef4444,
      });
      const marker = new THREE.Mesh(sphereGeo, sphereMat);
      marker.position.copy(localPt);
      worldGroupRef.current.add(marker);
      transectObjectsRef.current.push(marker);

      const newPts = [...transectPointsRef.current, { pt: localPt, uv }];
      transectPointsRef.current = newPts;

      if (newPts.length === 2) {
        const lineGeo = new THREE.BufferGeometry().setFromPoints([
          newPts[0].pt,
          newPts[1].pt,
        ]);
        const lineMat = new THREE.LineBasicMaterial({ color: 0x38bdf8, linewidth: 2 });
        const line = new THREE.Line(lineGeo, lineMat);
        worldGroupRef.current.add(line);
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

        const cellX = meta.cell_size_m ? meta.cell_size_m[0] : 2;
        const cellY = meta.cell_size_m ? meta.cell_size_m[1] : 2;
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
    zoomRef.current = Math.max(60, Math.min(600, zoomRef.current + e.deltaY * 0.35));
    if (cameraRef.current) {
      cameraRef.current.position.z = zoomRef.current;
      cameraRef.current.position.y = zoomRef.current * 0.55;
    }
  };

  const resetView = () => {
    rotationRef.current = { x: 0.65, y: -0.75 };
    panRef.current = { x: 0, y: -20 };
    zoomRef.current = 260;
    if (cameraRef.current) {
      cameraRef.current.position.set(0, 140, 260);
      cameraRef.current.lookAt(0, 0, 0);
    }
    setExaggeration(meta && checkIsLidar(meta) ? 1.0 : 1.8);
    setWireframe(false);
  };

  if (!isOpen) return null;

  const isLidarModel = Boolean(meta && checkIsLidar(meta));

  return (
    <div className="fixed inset-0 z-[1300] bg-black/80 backdrop-blur-md flex items-center justify-center p-5">
      <div className="relative w-full max-w-[1040px] bg-card border border-border rounded-xl shadow-2xl overflow-hidden flex flex-col">
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
            className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted transition-colors cursor-pointer"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* 3D Canvas Mount Area */}
        <div
          style={{
            cursor: measuring ? 'crosshair' : isDraggingRef.current ? 'grabbing' : 'grab',
          }}
          className="relative w-full h-[490px] bg-background"
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onWheel={handleWheel}
          onContextMenu={(e) => e.preventDefault()}
        >
          <div ref={mountRef} className="w-full h-full" />

          {loading && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-sky-400 bg-background/90">
              <Loader2 className="h-7 w-7 animate-spin" />
              <span className="text-xs font-mono">Constructing 3D Scene (Terrain, Water, Buildings & Canopy)...</span>
            </div>
          )}

          {error && (
            <div className="absolute inset-0 flex flex-col items-center justify-center text-rose-400 p-6 text-center gap-2">
              <AlertTriangle className="h-6 w-6" />
              <span className="text-xs font-mono">{error}</span>
            </div>
          )}

          <div className="absolute bottom-3 left-3.5 bg-card/90 border border-border px-2.5 py-1.5 rounded-lg text-muted-foreground text-[10.5px] font-mono pointer-events-none">
            {measuring
              ? 'TRANSECT MODE: Click Point A, then Point B on the 3D surface'
              : 'Left Drag: Rotate | Right Drag: Pan | Scroll: Zoom'}
          </div>
        </div>

        {/* Real-Time Transect Profile Drawer (if measured) */}
        {transectResult && (
          <div className="bg-background border-t border-border px-4 py-2.5 text-[11px] font-mono text-muted-foreground">
            <div className="flex items-center justify-between mb-1.5">
              <div className="flex items-center gap-3.5 flex-wrap">
                <span className="text-sky-400 font-semibold">3D Slice Cross-Section:</span>
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
                className="border border-border text-muted-foreground hover:text-foreground px-2 py-0.5 rounded-md text-[10px] cursor-pointer"
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
                    <polygon points={area} fill="#38BDF8" fillOpacity="0.2" />
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
              className="bg-muted text-foreground border border-border rounded-lg px-2 py-1 text-[11.5px] cursor-pointer outline-none"
            >
              {meta?.orthophoto_url && (
                <option value={meta.orthophoto_url}>
                  True-Color Aerial Photo (Roads, Water & Roofs)
                </option>
              )}
              <option value="realistic_urban">
                Photorealistic Urban (Roads, Buildings & Foliage)
              </option>
              <option value="lidar_canopy">LiDAR Canopy, Roads & Buildings (CHM)</option>
              <option value="lidar_discrete">
                LiDAR Discrete Objects (Ground / Trees / Roofs)
              </option>
              <option value="desert">Desert Sand & Mountain Crags</option>
              <option value="topographic">Topographic Relief (Green to Snow)</option>
              <option value="urban">Urban & Roads (Structural Contrast)</option>
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
                    Drape: {baseName}
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
              className="w-[100px] cursor-pointer accent-primary"
            />
            <span className="font-mono text-sky-400 font-semibold min-w-[32px]">
              {exaggeration.toFixed(1)}x
            </span>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-2">
            {/* Solid 3D Objects vs Point Cloud Mode Toggle */}
            <div className="flex items-center bg-muted p-0.5 rounded-lg border border-border">
              <button
                type="button"
                onClick={() => setRenderMode('surface')}
                title="3D Terrain + Extruded Buildings + Canopy"
                className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium transition-colors cursor-pointer ${
                  renderMode === 'surface'
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                <Globe className="h-3 w-3" />
                Surface
              </button>
              <button
                type="button"
                onClick={() => setRenderMode('points')}
                title="Multi-Return 3D Point Cloud"
                className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium transition-colors cursor-pointer ${
                  renderMode === 'points'
                    ? 'bg-primary text-primary-foreground'
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
              className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border border-border text-[11.5px] transition-colors cursor-pointer ${
                measuring
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted text-foreground hover:bg-muted/80'
              }`}
            >
              <MapPin className="h-3 w-3" />
              <span>{measuring ? 'Measuring (Click 3D)' : 'Slice Profile'}</span>
            </button>

            <button
              type="button"
              onClick={() => setWireframe((prev) => !prev)}
              className={`px-2.5 py-1 rounded-lg border border-border text-[11.5px] transition-colors cursor-pointer ${
                wireframe
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted text-foreground hover:bg-muted/80'
              }`}
            >
              {wireframe ? 'Solid Surface' : 'Wireframe'}
            </button>

            <button
              type="button"
              onClick={resetView}
              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-muted border border-border text-foreground hover:bg-muted/80 text-[11.5px] transition-colors cursor-pointer"
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
