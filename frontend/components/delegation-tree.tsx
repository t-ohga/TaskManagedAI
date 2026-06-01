type TreeNode = {
  id: string;
  role: string | null;
  status: string;
  children: TreeNode[];
};

type DelegationTreeProps = {
  root: TreeNode;
};

const STATUS_COLORS: Record<string, string> = {
  running: "border-amber-400 bg-amber-50",
  completed: "border-emerald-400 bg-emerald-50",
  failed: "border-red-400 bg-red-50",
  cancelled: "border-gray-400 bg-gray-100",
  blocked: "border-orange-400 bg-orange-50",
};

function TreeNodeView({ node, depth }: { node: TreeNode; depth: number }) {
  const color = STATUS_COLORS[node.status] ?? "border-line bg-panel";
  return (
    <div className={depth > 0 ? "ml-6 border-l-2 border-line pl-4" : ""}>
      <div className={`inline-flex items-center gap-2 rounded-md border-2 px-3 py-1.5 text-xs ${color}`}>
        <span className="font-mono">{node.id.slice(0, 6)}</span>
        {node.role ? <span className="rounded bg-white/60 px-1.5 py-0.5 text-[10px] font-medium">{node.role}</span> : null}
        <span className="text-muted-foreground">{node.status}</span>
      </div>
      {node.children.length > 0 ? <div className="mt-2 grid gap-2">
          {node.children.map((child) => (
            <TreeNodeView key={child.id} node={child} depth={depth + 1} />
          ))}
        </div> : null}
    </div>
  );
}

export function DelegationTree({ root }: DelegationTreeProps) {
  return (
    <div className="overflow-x-auto" aria-label="Delegation ツリー">
      <TreeNodeView node={root} depth={0} />
    </div>
  );
}
