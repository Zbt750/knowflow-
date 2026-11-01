import type { KnowledgeNodeView } from '../types/practice';

export interface KnowledgeTreeEntry {
  key: string;
  node: KnowledgeNodeView;
  depth: number;
  side: -1 | 1;
  x: number;
  y: number;
  parentId: string | null;
  moreFor?: string;
  remaining?: number;
}
export interface KnowledgeTreeEdge { key: string; d: string; targetId: string; jointX: number; jointY: number; isRoot: boolean; }

function layoutCompactKnowledgeTree(
  roots: KnowledgeNodeView[],
  isOpen: (node: KnowledgeNodeView) => boolean,
  limits: Record<string, number>,
  batchSize: number,
  viewportWidth: number,
) {
  const width = Math.max(280, viewportWidth);
  const nodeWidth = Math.min(300, width - 32);
  // 窄屏下把奶蛙和最初三个根节点放进首屏；后代展开后再向下延伸。
  const rowHeight = 78;
  const groupGap = 6;
  const top = 260;
  const take = (node: KnowledgeNodeView) => Math.max(1, limits[node.id] ?? batchSize);
  const visibleChildren = (node: KnowledgeNodeView) => isOpen(node) ? node.children.slice(0, take(node)) : [];
  const rowCounts = new Map<string, number>();
  const countRows = (node: KnowledgeNodeView): number => {
    const children = visibleChildren(node);
    const count = 1 + children.reduce((total, child) => total + countRows(child), 0)
      + Number(isOpen(node) && node.children.length > children.length);
    rowCounts.set(node.id, count);
    return count;
  };
  roots.forEach(countRows);

  const nodes: KnowledgeTreeEntry[] = [];
  let groupTop = top;
  const visit = (node: KnowledgeNodeView, depth: number, parentId: string | null, side: -1 | 1, rowTop: number): number => {
    const y = rowTop + rowHeight / 2;
    const x = width / 2 + (depth === 0 ? 0 : side * Math.min(42, 22 + depth * 4));
    nodes.push({ key: node.id, node, depth, side, x, y, parentId });
    let childTop = rowTop + rowHeight;
    const children = visibleChildren(node);
    children.forEach((child, index) => {
      const childSide: -1 | 1 = index % 2 === 0 ? -1 : 1;
      visit(child, depth + 1, node.id, childSide, childTop);
      childTop += (rowCounts.get(child.id) ?? 1) * rowHeight;
    });
    if (isOpen(node) && node.children.length > children.length) {
      const yMore = childTop + rowHeight / 2;
      nodes.push({
        key: `more-${node.id}`, node, depth: depth + 1, side,
        x: width / 2 + side * 38, y: yMore, parentId: node.id,
        moreFor: node.id, remaining: node.children.length - children.length,
      });
    }
    return y;
  };
  roots.forEach((root, index) => {
    visit(root, 0, null, index % 2 === 0 ? -1 : 1, groupTop);
    groupTop += (rowCounts.get(root.id) ?? 1) * rowHeight + groupGap;
  });

  const byId = new Map(nodes.filter(row => !row.moreFor).map(row => [row.node.id, row]));
  const nodeRows = nodes.filter(row => !row.moreFor);
  const rootAnchors = [[6, -190], [228, -225], [308, -46]];
  const figureScale = 0.28;
  const figureY = 135;
  const edges = nodes.flatMap<KnowledgeTreeEdge>(row => {
    if (row.moreFor) {
      const parent = byId.get(row.parentId ?? '');
      if (!parent) return [];
      const x1 = parent.x;
      const y1 = parent.y + rowHeight / 2;
      const x2 = row.x - row.side * nodeWidth / 2;
      const y2 = row.y;
      const bend = (y1 + y2) / 2;
      return [{ key: row.key, targetId: row.node.id, isRoot: false, jointX: x2, jointY: y2,
        d: `M${x1} ${y1} C${x1} ${bend},${x2} ${bend},${x2} ${y2}` }];
    }
    if (!row.parentId) {
      const rootIndex = roots.findIndex(root => root.id === row.node.id);
      const anchor = rootAnchors[rootIndex % rootAnchors.length];
      const x1 = width / 2 + anchor[0] * figureScale;
      const y1 = figureY + anchor[1] * figureScale;
      const x2 = width / 2 - nodeWidth / 2;
      const y2 = row.y - rowHeight / 2;
      const bend = (y1 + y2) / 2;
      return [{ key: `root-${row.key}`, targetId: row.node.id, isRoot: true, jointX: x2, jointY: row.y,
        d: `M${x1} ${y1} C${x1} ${bend},${x2} ${bend},${x2} ${y2}` }];
    }
    const parent = byId.get(row.parentId);
    if (!parent) return [];
    const x1 = parent.x + row.side * nodeWidth / 2;
    const y1 = parent.y + rowHeight / 2;
    const x2 = row.x - row.side * nodeWidth / 2;
    const y2 = row.y - rowHeight / 2;
    const bend = (y1 + y2) / 2;
    return [{ key: row.key, targetId: row.node.id, isRoot: false, jointX: x2, jointY: row.y,
      d: `M${x1} ${y1} C${x1} ${bend},${x2} ${bend},${x2} ${y2}` }];
  });
  return { nodes, edges, width, height: Math.max(520, groupTop + 16), compact: true, nodeWidth, figureScale, figureY };
}

/** 仅排版后端知识层级；不合并节点，不推导掌握度，也不读取业务数据。 */
export function layoutKnowledgeTree(
  roots: KnowledgeNodeView[],
  isOpen: (node: KnowledgeNodeView) => boolean,
  limits: Record<string, number> = {},
  batchSize = 20,
  compact = false,
  viewportWidth = 800,
) {
  if (compact) return layoutCompactKnowledgeTree(roots, isOpen, limits, batchSize, viewportWidth);
  let maxDepth = 0;
  const counts = new Map<string, number>();
  const take = (node: KnowledgeNodeView) => Math.max(1, limits[node.id] ?? batchSize);
  const count = (node: KnowledgeNodeView, depth: number): number => {
    maxDepth = Math.max(maxDepth, depth);
    const children = isOpen(node) ? node.children.slice(0, take(node)) : [];
    const size = children.length
      ? children.reduce((total, child) => total + count(child, depth + 1), 0) + Number(node.children.length > children.length)
      : 1;
    counts.set(node.id, size);
    return size;
  };
  // 三条真实根分支分别从原角色图三个脚趾锚点伸出；每个根节点及后代都来自 API。
  const anchors = [[6, -190], [228, -225], [308, -46]];
  const lanes: [KnowledgeNodeView[], KnowledgeNodeView[], KnowledgeNodeView[]] = [[], [], []];
  roots.forEach((node, index) => { count(node, 0); lanes[index % 3].push(node); });
  const laneSpan = lanes.map(laneRoots => laneRoots.reduce(
    (total, node) => total + (counts.get(node.id) ?? 1) * 78,
    Math.max(0, laneRoots.length - 1) * 112,
  ));
  const rootOffset = 430;
  const toeOffset = 720;
  const levelSpacing = 300;
  const rootSides = new Map<string, -1 | 1>();
  lanes.forEach((sideRoots, laneIndex) => sideRoots.forEach(node => {
    rootSides.set(node.id, laneIndex === 0 ? -1 : 1);
  }));
  const width = Math.max(1300, 2 * (rootOffset + maxDepth * levelSpacing + 125));
  const height = Math.max(1100, laneSpan[0] + 800, laneSpan[1] + laneSpan[2] + 912);
  const rootCenters = new Map<string, number>();
  lanes.forEach((sideRoots, laneIndex) => {
    let offset = height / 2 + (laneIndex === 2 ? 60 : -300) - laneSpan[laneIndex] / 2;
    if (laneIndex === 2 && lanes[1].length) {
      const previousBottom = Math.max(...lanes[1].map(root => rootCenters.get(root.id)! + (counts.get(root.id) ?? 1) * 39));
      offset = Math.max(offset, previousBottom + 112);
    }
    for (const root of sideRoots) {
      const span = (counts.get(root.id) ?? 1) * 78;
      rootCenters.set(root.id, offset + span / 2);
      offset += span + 112;
    }
  });
  const nodes: KnowledgeTreeEntry[] = [];
  const cursorByRoot = new Map<string, number>();
  for (let laneIndex = 0; laneIndex < 3; laneIndex++) {
    const side = (laneIndex === 0 ? -1 : 1) as -1 | 1;
    const visit = (node: KnowledgeNodeView, depth: number, parentId: string | null, rootId: string): number => {
      const children = isOpen(node) ? node.children.slice(0, take(node)) : [];
      const positions = children.map(child => visit(child, depth + 1, node.id, rootId));
      if (children.length && node.children.length > children.length) {
        const y = cursorByRoot.get(rootId) ?? (rootCenters.get(rootId) ?? height / 2);
        cursorByRoot.set(rootId, y + 78);
        const branchOffset = rootOffset;
        nodes.push({key:`more-${node.id}`,node,depth:depth+1,side,x:width/2+side*(branchOffset+(depth+1)*levelSpacing),y,parentId:node.id,moreFor:node.id,remaining:node.children.length-children.length});
        positions.push(y);
      }
      const y = depth === 0 ? rootCenters.get(node.id)! : positions.length ? (positions[0] + positions[positions.length - 1]) / 2 : (cursorByRoot.get(rootId) ?? rootCenters.get(rootId) ?? height / 2);
      if (!positions.length) cursorByRoot.set(rootId, (cursorByRoot.get(rootId) ?? y) + 78);
      const xOffset = depth === 0 ? rootOffset : depth === 1 ? toeOffset : rootOffset + depth * levelSpacing;
      nodes.push({key:node.id,node,depth,side,x:width/2+side*xOffset,y,parentId});
      return y;
    };
    lanes[laneIndex].forEach(node => {
      cursorByRoot.set(node.id, (rootCenters.get(node.id) ?? height / 2) - Math.max(0, (counts.get(node.id) ?? 1) - 2) * 39);
      visit(node, 0, null, node.id);
    });
  }
  const rowsByParent = new Map<string, KnowledgeTreeEntry[]>();
  for (const row of nodes) if (row.parentId) rowsByParent.set(row.parentId, [...(rowsByParent.get(row.parentId) ?? []), row]);
  const rootRows = nodes.filter(row => !row.moreFor && row.depth === 0);
  for (const root of rootRows) {
    root.side = rootSides.get(root.node.id) ?? root.side;
    const directRows = rowsByParent.get(root.node.id) ?? [];
    const childOrder = new Map(root.node.children.map((child,index)=>[child.id,index]));
    directRows.sort((a,b)=>{
      const ai=a.moreFor?root.node.children.length:(childOrder.get(a.node.id)??Number.MAX_SAFE_INTEGER);
      const bi=b.moreFor?root.node.children.length:(childOrder.get(b.node.id)??Number.MAX_SAFE_INTEGER);
      return ai-bi;
    });
    root.x = width/2 + root.side*rootOffset;
    root.y = rootCenters.get(root.node.id)!;
    const weights = directRows.map(child => child.moreFor ? 1 : counts.get(child.node.id) ?? 1);
    let nextY = root.y - weights.reduce((total, weight) => total + weight, 0) * 78 / 2;
    directRows.forEach((child,index)=>{
      // 已展开子树需要保留它的完整高度，不能把多层节点压在同一脚趾间距里。
      const targetY=nextY + weights[index]*78/2;
      nextY+=weights[index]*78;
      const delta=targetY-child.y;
      child.x=width/2+child.side*toeOffset;
      child.y=targetY;
      if(child.moreFor)return;
      const shiftDescendants=(parentId:string)=>{
        for(const descendant of rowsByParent.get(parentId)??[]){
          descendant.y+=delta;
          if(!descendant.moreFor)shiftDescendants(descendant.node.id);
        }
      };
      shiftDescendants(child.node.id);
    });
  }
  // 子孙从脚趾继续向外生长；路径始终来自实际 KnowledgePoint 父子关系。
  for(const row of nodes)if(row.depth>=2)row.x=width/2+row.side*(rootOffset+row.depth*levelSpacing);
  const byId = new Map(nodes.filter(node => !node.moreFor).map(node => [node.node.id,node]));
  const edges = nodes.flatMap<KnowledgeTreeEdge>(node => {
    const parent = node.parentId ? byId.get(node.parentId) : undefined;
    // 顶层根从脚部延伸；其它枝杈严格保持后端提供的真实父子关系。
    if (!parent) {
      // 每个顶层知识分支直接接到奶蛙图像中对应的三个脚趾锚点。
      const rootIndex = roots.findIndex(root => root.id === node.node.id);
      const anchor = anchors[rootIndex % anchors.length];
      const x1=width/2+anchor[0], y1=height/2+anchor[1];
      const x2=node.x-node.side*138;
      const c1x=rootIndex%3===0?x1-20:x1+142;
      // 左侧第一枝绕开角色上缘，但保持在画布内，不让线从视口外突然冒出。
      const c1y=rootIndex%3===0?Math.min(y1,node.y)-60:rootIndex%3===1?y1-36:y1+86;
      const c2x=node.x-node.side*180;
      const c2y=rootIndex%3===0?c1y:node.y;
      return [{key:`root-${node.key}`,targetId:node.node.id,isRoot:true,jointX:x2,jointY:node.y,d:`M${x1} ${y1} C${c1x} ${c1y},${c2x} ${c2y},${x2} ${node.y}`}];
    }
    const x1 = parent.x + node.side * 136;
    const x2 = node.x - node.side * 144;
    const mid = (x1+x2)/2;
    return [{key:node.key,targetId:node.node.id,isRoot:false,jointX:x2,jointY:node.y,d:`M${x1} ${parent.y} C${mid} ${parent.y},${mid} ${node.y},${x2} ${node.y}`}];
  });
  return {nodes,edges,width,height,compact:false,nodeWidth:244,figureScale:1,figureY:height/2};
}
