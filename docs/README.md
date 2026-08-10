# AI Optimizer Documentation

This site is built with [Docusaurus](https://docusaurus.io/). Documentation source files are in `content/`.

## Local Development

From this directory, run:

```bash
npm ci
npm run start
```

The development server reloads when documentation or site assets change.

## Documentation Images

Organize images by ownership rather than placing every image in `static/img`.

- Use `static/img/` for site-wide branding and user-interface assets, such as the logo, favicon, and social card.
- Use a section's `assets/` directory for images owned by that section.
- Use `content/assets/` only for documentation images shared by unrelated sections.

For example:

```text
content/
  client/
    chatbot.mdx
    assets/
      chatbot/
        history-and-context.png
  advanced/
    iac.md
    assets/
      iac/
        architecture.png
  assets/
    architecture/
      shared-diagram.png
```

Reference section-owned images with a relative Markdown path:

```md
![History and context settings](./assets/chatbot/history-and-context.png)
```

Use lowercase, hyphenated, descriptive filenames. Provide meaningful alternative text for each image, and avoid page-number or otherwise opaque names.

See the [Docusaurus asset documentation](https://docusaurus.io/docs/markdown-features/assets) for additional image and asset options.
