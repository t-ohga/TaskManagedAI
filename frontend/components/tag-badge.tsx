type TagBadgeProps = {
  tags: string[];
};

const TAG_COLORS = [
  "bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300",
  "bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-300",
  "bg-pink-100 dark:bg-pink-900/40 text-pink-700 dark:text-pink-300",
  "bg-teal-100 dark:bg-teal-900/40 text-teal-700 dark:text-teal-300",
  "bg-orange-100 dark:bg-orange-900/40 text-orange-700 dark:text-orange-300",
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
