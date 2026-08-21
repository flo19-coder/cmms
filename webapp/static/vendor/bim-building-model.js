// Shared BIM-style office tower + annex, built from named meshes.
// createBuilding(THREE) -> { group, columns: [...], pipes: [...], floors: [...] }
// columns/pipes animate first (structural frame), floors animate after (envelope going up).
export function createBuilding(THREE) {
  const group = new THREE.Group();
  group.name = 'CMMS_Building';

  const glassMat = new THREE.MeshStandardMaterial({ color: 0x5980a6, metalness: 0.3, roughness: 0.35, transparent: true, opacity: 0.88 });
  const frameMat = new THREE.MeshStandardMaterial({ color: 0xdfe1e2, metalness: 0.15, roughness: 0.75 });
  const annexMat = new THREE.MeshStandardMaterial({ color: 0xc9cbcc, metalness: 0.05, roughness: 0.9 });
  const redMat = new THREE.MeshStandardMaterial({ color: 0xb23a2e, metalness: 0.1, roughness: 0.6 });
  const roofMat = new THREE.MeshStandardMaterial({ color: 0x53575a, metalness: 0.2, roughness: 0.7 });
  const colMat = new THREE.MeshStandardMaterial({ color: 0x8b9196, metalness: 0.4, roughness: 0.5 });
  const pipeMat = new THREE.MeshStandardMaterial({ color: 0x5980a6, metalness: 0.5, roughness: 0.3 });
  const lineMat = new THREE.LineBasicMaterial({ color: 0x2c3e50, transparent: true, opacity: 0.55 });
  const mullionMat = new THREE.MeshStandardMaterial({ color: 0xeceded, metalness: 0.2, roughness: 0.6 });

  const columns = [];
  const pipes = [];
  const floors = [];

  function addFloorEdges(mesh, w, h, d) {
    const edges = new THREE.EdgesGeometry(new THREE.BoxGeometry(w, h, d));
    const line = new THREE.LineSegments(edges, lineMat);
    mesh.add(line);
  }

  // Base plinth
  const plinth = new THREE.Mesh(new THREE.BoxGeometry(20, 0.4, 13), roofMat);
  plinth.position.y = -0.2;
  plinth.name = 'plinth';
  group.add(plinth);
  // Curb detail
  const curb = new THREE.Mesh(new THREE.BoxGeometry(20.4, 0.12, 13.4), colMat);
  curb.position.y = -0.42;
  group.add(curb);

  const towerW = 9, towerD = 7.5, floorH = 0.85, towerFloors = 15;
  const towerX = -3.2;
  const towerTopY = towerFloors * floorH;

  // --- Structural columns (corners + mid-span) ---
  const colRadius = 0.16;
  const colXs = [-towerW / 2, -towerW / 6, towerW / 6, towerW / 2];
  const colZs = [-towerD / 2, towerD / 2];
  colXs.forEach((cx) => {
    colZs.forEach((cz) => {
      const geo = new THREE.CylinderGeometry(colRadius, colRadius, towerTopY, 10);
      const col = new THREE.Mesh(geo, colMat);
      col.position.set(towerX + cx, towerTopY / 2, cz);
      col.name = 'column';
      col.scale.y = 0.001;
      group.add(col);
      columns.push({ obj: col, fullHeight: towerTopY, baseY: towerTopY / 2 });
    });
  });

  // --- MEP riser pipes near the core ---
  [[-0.6, 0], [0.6, 0], [0, 0.9]].forEach(([ox, oz]) => {
    const h = towerTopY * 0.98;
    const geo = new THREE.CylinderGeometry(0.09, 0.09, h, 8);
    const pipe = new THREE.Mesh(geo, pipeMat);
    pipe.position.set(towerX + ox, h / 2, oz);
    pipe.name = 'mep_riser';
    pipe.scale.y = 0.001;
    group.add(pipe);
    pipes.push({ obj: pipe, fullHeight: h, baseY: h / 2 });
  });

  // --- Main glass tower floors ---
  for (let i = 0; i < towerFloors; i++) {
    const isGround = i === 0;
    const f = new THREE.Group();
    f.name = 'tower_floor_' + i;
    const bodyMat = isGround ? redMat : glassMat;
    const body = new THREE.Mesh(new THREE.BoxGeometry(towerW, floorH * 0.88, towerD), bodyMat);
    f.add(body);
    // floor slab
    const slab = new THREE.Mesh(new THREE.BoxGeometry(towerW + 0.15, floorH * 0.12, towerD + 0.15), frameMat);
    slab.position.y = -floorH * 0.44;
    f.add(slab);
    // vertical mullions
    for (let m = -3; m <= 3; m++) {
      const mullion = new THREE.Mesh(new THREE.BoxGeometry(0.05, floorH * 0.86, 0.05), mullionMat);
      mullion.position.set((m / 3) * (towerW / 2 - 0.3), 0, towerD / 2);
      f.add(mullion);
    }
    addFloorEdges(body, towerW, floorH * 0.88, towerD);
    const targetY = i * floorH;
    f.position.set(towerX, targetY, 0);
    f.scale.y = 0.001;
    group.add(f);
    floors.push({ obj: f, targetY, height: floorH * 0.88 });
  }

  // Rooftop mechanical blocks + parapet
  const roof1 = new THREE.Mesh(new THREE.BoxGeometry(3.2, 0.9, 2.6), roofMat);
  roof1.position.set(towerX - 1.6, towerTopY + 0.45, 0.6);
  roof1.name = 'roof_plant_1';
  group.add(roof1);
  const roof2 = new THREE.Mesh(new THREE.BoxGeometry(1.6, 0.6, 1.6), roofMat);
  roof2.position.set(towerX + 2, towerTopY + 0.3, -1.2);
  roof2.name = 'roof_plant_2';
  group.add(roof2);
  const parapetGeo = new THREE.BoxGeometry(towerW + 0.2, 0.25, towerD + 0.2);
  const parapetEdges = new THREE.EdgesGeometry(parapetGeo);
  const parapet = new THREE.LineSegments(parapetEdges, lineMat);
  parapet.position.set(towerX, towerTopY + 0.12, 0);
  group.add(parapet);

  // --- Attached lower annex ---
  const annexW = 6, annexD = 7.5, annexFloorH = 0.75, annexFloors = 7;
  const annexX = towerX + towerW / 2 + annexW / 2 + 0.3;
  const annexTopY = annexFloors * annexFloorH;

  const acolXs = [-annexW / 2, annexW / 2];
  acolXs.forEach((cx) => {
    colZs.forEach((cz) => {
      const geo = new THREE.CylinderGeometry(colRadius * 0.9, colRadius * 0.9, annexTopY, 10);
      const col = new THREE.Mesh(geo, colMat);
      col.position.set(annexX + cx, annexTopY / 2, cz);
      col.name = 'annex_column';
      col.scale.y = 0.001;
      group.add(col);
      columns.push({ obj: col, fullHeight: annexTopY, baseY: annexTopY / 2 });
    });
  });

  for (let i = 0; i < annexFloors; i++) {
    const isGround = i === 0;
    const f = new THREE.Group();
    f.name = 'annex_floor_' + i;
    const bodyMat = isGround ? redMat : annexMat;
    const body = new THREE.Mesh(new THREE.BoxGeometry(annexW, annexFloorH * 0.86, annexD), bodyMat);
    f.add(body);
    const slab = new THREE.Mesh(new THREE.BoxGeometry(annexW + 0.1, annexFloorH * 0.1, annexD + 0.1), frameMat);
    slab.position.y = -annexFloorH * 0.43;
    f.add(slab);
    addFloorEdges(body, annexW, annexFloorH * 0.86, annexD);
    const targetY = i * annexFloorH;
    f.position.set(annexX, targetY, 0);
    f.scale.y = 0.001;
    group.add(f);
    floors.push({ obj: f, targetY, height: annexFloorH * 0.86 });
  }

  group.position.y = 0;
  return { group, columns, pipes, floors };
}
