import React, {type ReactNode, useEffect, useRef} from 'react';

import {useColorMode} from '@docusaurus/theme-common';
import useBaseUrl from '@docusaurus/useBaseUrl';

const githubButtonsScriptId = 'github-buttons-script';
const repositoryUrl = 'https://github.com/oracle/ai-optimizer';

type GithubButtons = {
  render: (anchor: HTMLAnchorElement, callback: (element: HTMLElement) => void) => void;
};

declare global {
  interface Window {
    githubButtons?: GithubButtons;
  }
}

function loadGithubButtons(scriptUrl: string): Promise<void> {
  if (window.githubButtons) {
    return Promise.resolve();
  }

  return new Promise((resolve) => {
    const existingScript = document.getElementById(githubButtonsScriptId) as HTMLScriptElement | null;

    if (existingScript) {
      existingScript.addEventListener('load', () => resolve(), {once: true});
      existingScript.addEventListener('error', () => resolve(), {once: true});
      return;
    }

    const script = document.createElement('script');
    script.id = githubButtonsScriptId;
    script.src = scriptUrl;
    script.async = true;
    script.addEventListener('load', () => resolve(), {once: true});
    script.addEventListener('error', () => resolve(), {once: true});
    document.body.appendChild(script);
  });
}

export default function GithubButtons(): ReactNode {
  const {colorMode} = useColorMode();
  const buttonsRef = useRef<HTMLDivElement>(null);
  const githubButtonsScriptUrl = useBaseUrl('/js/github-buttons.js');

  useEffect(() => {
    let cancelled = false;

    void loadGithubButtons(githubButtonsScriptUrl).then(() => {
      if (cancelled) {
        return;
      }

      buttonsRef.current?.querySelectorAll<HTMLAnchorElement>('a[data-github-button]').forEach((anchor) => {
        window.githubButtons?.render(anchor, (button) => {
          anchor.parentNode?.replaceChild(button, anchor);
        });
      });
    });

    return () => {
      cancelled = true;
    };
  }, [colorMode, githubButtonsScriptUrl]);

  return (
    <div className="doc-sidebar-github-buttons" key={colorMode} ref={buttonsRef}>
      <a
        aria-label="Download the AI Optimizer from GitHub"
        data-color-scheme={colorMode}
        data-github-button
        data-icon="octicon-cloud-download"
        href={`${repositoryUrl}/releases/latest`}
      >
        Download
      </a>
      <a
        aria-label="Star the AI Optimizer on GitHub"
        data-color-scheme={colorMode}
        data-github-button
        data-icon="octicon-star"
        data-show-count="true"
        href={repositoryUrl}
      >
        Star
      </a>
      <a
        aria-label="Fork the AI Optimizer on GitHub"
        data-color-scheme={colorMode}
        data-github-button
        data-icon="octicon-repo-forked"
        data-show-count="true"
        href={`${repositoryUrl}/fork`}
      >
        Fork
      </a>
    </div>
  );
}
