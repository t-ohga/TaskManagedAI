type TagBadgeProps = {
  tags: string[];
};

const TAG_COLORS = [
  "bg-blue-100 text-blue-700",
  "bg-purple-100 text-purple-700",
  "bg-pink-100 text-pink-700",
  "bg-teal-100 text-teal-700",
  "bg-orange-100 text-orange-700",
];

export function TagBadge({ tags }: TagBadgeProps) {
  if (tags.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-1">
      {tags.map((tag, i) => (
        <span
          key={tag}
          className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${TAG_COLORS[i % TAG_COLORS.length]}`}
        >
          {tag}
        </span>
      ))}
    </div>
  );
}
