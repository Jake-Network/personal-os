export interface SlashPlaybook {
  slug: string;
  title: string;
  summary: string;
}

/**
 * Playbooks a leading `/word` could mean. The server reads `/slug` from the message itself,
 * so completing it is the only client-side work; nothing here decides what is shared.
 */
export function slashSuggestions(input: string, playbooks: SlashPlaybook[], limit = 6): SlashPlaybook[] {
  const match = /^\/([^\s/]*)$/.exec(input);
  if (!match) return [];
  const term = match[1].toLowerCase();
  return playbooks
    .filter(p => p.slug.toLowerCase().startsWith(term) || (term.length > 0 && p.title.toLowerCase().includes(term)))
    .slice(0, limit);
}

export function completeSlash(slug: string): string {
  return `/${slug} `;
}
