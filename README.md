# linkedin-bot

**An AI-assisted, human-approved publishing pipeline for my personal LinkedIn profile.**

It turns my written notes and the activity of my public GitHub projects into post
drafts, opens each draft as a Pull Request for me to review and edit, and publishes only
what I merge, through LinkedIn's official API. Everything runs on GitHub Actions.

🇪🇸 [Léeme en español](README.es.md)

---

## Why

I wanted consistent, credible visibility on LinkedIn without handing my profile to an
autonomous bot. Generic AI text is easy to spot and one bad post costs more credibility
than ten good ones earn, so the design rule is simple: **the AI drafts, I decide.**

## What it does

```
 SOURCES                    GENERATOR                  REVIEW (me)              PUBLISHER
 ─────────                  ─────────                  ───────────              ─────────
 content/ideas/*.md   ──►   LLM + voice profile  ──►   one Pull Request   ──►   LinkedIn API
 (my notes)                 + factuality rules         per draft                (create post)
                            + automatic fact check     edit → merge = yes       max 1/day
 watched GitHub repos                                  close = no               record URN
 (README, commits,                                                              in the repo
  changed files)
```

1. **Notes** — I drop a note in `content/ideas/`. The generator drafts a post from it.
2. **Projects** — for each repo in `config/watched_repos.yml` the generator writes an
   introduction post first, then at most one update post per week when there are new
   commits (it reads commit messages and the list of changed files).
3. **Review** — every draft becomes its own Pull Request, with the source material and an
   automatic fact-check report that flags claims the material does not support.
4. **Publish** — merging the PR approves the post; `publish.yml` publishes it (at most one
   post per UTC day) and moves the file to `content/published/` with its LinkedIn URN.

## Guarantees (enforced in code, not by convention)

| Guarantee | How |
|---|---|
| **Nothing is published without my approval** | Before publishing, the publisher asks the GitHub API whether the commit that added the post file belongs to a merged PR. A file pushed directly to the queue is refused. |
| **A post is published at most once** | The post is *claimed* (`status: publishing`) and pushed **before** calling LinkedIn. If a run dies halfway, the post stays blocked for manual review instead of being retried blindly. |
| **At most one post per day** | Selection checks the published log for the current UTC day. |
| **No invented facts** | Non-negotiable prompt rules live in code (not in the editable style file): only facts from the material, no invented numbers, circumstances or comparisons, figures kept in their context. A second AI pass lists doubtful claims in the PR. |
| **Publish-only scope** | The only LinkedIn write call is "create post". No likes, comments, messages, feed reading or scraping. Official API only. |
| **No duplicate drafts** | Each note/repo maps to a deterministic branch name; existing PRs (open, merged or closed = rejected) are checked first. No state file. |

## How it is built

| Area | Choice |
|---|---|
| Language | Python 3.12, managed with [uv](https://docs.astral.sh/uv/) |
| HTTP | httpx (every external call is mocked in tests) |
| LLM | Groq (`openai/gpt-oss-120b`) behind a provider-agnostic `LLMClient` interface; model and parameters in `config/llm.yml` |
| LinkedIn | Official REST API: Posts API with `w_member_social`; OpenID Connect for the member id |
| Storage | Markdown files with YAML frontmatter in this repo — no database |
| Runtime | GitHub Actions (push triggers, daily schedules, manual runs) |
| Tests | pytest (unit tests plus git operations against real temporary repositories) |

```
src/linkedin_bot/
├── auth/        local OAuth helper to obtain the LinkedIn token (never runs in CI)
├── sources/     reads public repo data (README, languages, commits, changed files)
├── generator/   prompts, voice profile, drafting, fact check, note/project runs
├── llm/         LLMClient interface + Groq client (retries on rate limits)
├── store/       post files: parse, validate, render, move queue → published
├── publisher/   selection rules, PR approval check, LinkedIn client, publish run
├── repo/        git CLI wrapper and GitHub REST client shared by both pipelines
└── ops/         token-expiry reminder
config/          llm.yml · voice_profile.md · watched_repos.yml · linkedin_token.yml
content/         ideas/ · queue/ · published/  (the published log is append-only)
```

| Workflow | Trigger | What it does |
|---|---|---|
| `generate.yml` | new note, change to watched repos, daily, manual | drafts posts and opens one PR per draft |
| `publish.yml` | merge into the queue, daily, manual | publishes the next approved, due post |
| `preview-draft.yml` | manual | prints a draft and its fact check for a note or a repo — opens nothing, publishes nothing |
| `llm-check.yml` | manual | one short generation to verify the LLM key and model |
| `token-reminder.yml` | daily, manual | opens a GitHub issue with renewal steps 14 days before the LinkedIn token expires |

## Running it yourself

1. **Create a LinkedIn developer app** and add the products *Share on LinkedIn* and
   *Sign In with LinkedIn using OpenID Connect*. Register the redirect URL
   `http://localhost:8765/callback`.
2. **Get a token locally:** `cp .env.example .env`, fill in the client id and secret,
   then run `uv run linkedin-bot-auth`, sign in and click *Allow*. It prints your member
   URN and the token expiry and saves the token to `.linkedin_token.json` (git-ignored).
   LinkedIn access tokens last 60 days; repeat this step before they expire. The helper
   also writes the new expiry to `config/linkedin_token.yml` (commit it) so the reminder
   workflow knows when to warn you.
3. **Repository secrets** (Settings → Secrets and variables → Actions):
   `LINKEDIN_ACCESS_TOKEN`, `LINKEDIN_MEMBER_URN`, `GROQ_API_KEY`.
4. **Repository settings:** allow GitHub Actions to create pull requests
   (Settings → Actions → General) and enable "Automatically delete head branches".
5. Edit `config/voice_profile.md` (your tone and 3+ example posts written by you) and
   `config/watched_repos.yml`.

Run the tests:

```bash
uv run pytest -q
```

## Status

- ✅ Publishing from the queue with approval check, idempotency and daily limit.
- ✅ Drafts from notes, one PR per draft, automatic fact check.
- ✅ Project introductions from watched repos; weekly update posts implemented.
- ✅ Automatic reminder (GitHub issue) before the LinkedIn token expires.
- 🔜 Next: image attachments and scheduled publishing in production.

## Non-goals

No likes, comments, connection requests, messages, feed reading or scraping. No browser
automation or unofficial APIs. No autonomous posting — every post goes through a merged
Pull Request.

---

Not affiliated with LinkedIn. Uses only LinkedIn's official API within its terms.
Licensed under the [MIT License](LICENSE).
