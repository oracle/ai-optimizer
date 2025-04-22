# Oracle AI Optimizer & Toolkit - Documentation

## Description

This directory contains the documentation for the the [**Oracle AI Optimizer & Toolkit**](https://github.com/oracle-samples/ai-explorer).

## Getting Started - Documentation

The **Oracle AI Optimizer & Toolkit** documentation is powered by [Hugo](https://gohugo.io/) using the [Relearn](https://github.com/McShelby/hugo-theme-relearn) theme.

To contribute to the documentation, install [Hugo](https://gohugo.io/installation/). Installation instructions vary per Operating System.

From the `docs` directory:

1. Download the [Relearn](https://github.com/McShelby/hugo-theme-relearn) theme
   ```bash
   mkdir -p themes/relearn
   ```

   ```bash
   curl -L $(curl -s https://api.github.com/repos/McShelby/hugo-theme-relearn/releases/latest \
      | grep "tarball_url" | cut -d '"' -f 4) \
      | tar -xz -C themes/relearn --strip-components=1 --exclude='*/exampleSite'
   ```

1. Start Hugo: `hugo serve`

This will serve the documentation on `http://localhost:1313/ai-explorer/` for review.
