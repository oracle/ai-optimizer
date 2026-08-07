import type {ReactNode} from 'react';

import {useDocsVersion} from '@docusaurus/plugin-content-docs/client';

const repositoryUrl = 'https://github.com/oracle/ai-optimizer';

type GitHubSourceLinkProps = {
  children: ReactNode;
  path: string;
  type?: 'blob' | 'tree';
};

function useGitHubRef(): string {
  const {version} = useDocsVersion();
  return version === 'current' ? 'main' : version;
}

export function GitHubSourceLink({children, path, type = 'blob'}: GitHubSourceLinkProps): ReactNode {
  const ref = useGitHubRef();

  return <a href={`${repositoryUrl}/${type}/${ref}/${path}`}>{children}</a>;
}

export function GitHubSourceExtract(): ReactNode {
  const ref = useGitHubRef();
  const archiveUrl =
    ref === 'main'
      ? `${repositoryUrl}/releases/latest/download/ai-optimizer-src.tar.gz`
      : `${repositoryUrl}/releases/download/${ref}/ai-optimizer-src.tar.gz`;

  return (
    <>
      <p>
        Download and extract the source for this documentation version into a new directory:{' '}
        <a href={archiveUrl}>TAR.GZ archive</a>
      </p>
      <pre>
        <code>{`curl -LO ${archiveUrl}
mkdir ai-optimizer
tar zxf ai-optimizer-src.tar.gz -C ai-optimizer

cd ai-optimizer`}</code>
      </pre>
    </>
  );
}

export function OciResourceManagerStackLink({children}: {children: ReactNode}): ReactNode {
  const ref = useGitHubRef();
  const archiveUrl =
    ref === 'main'
      ? `${repositoryUrl}/releases/latest/download/ai-optimizer-iac.zip`
      : `${repositoryUrl}/releases/download/${ref}/ai-optimizer-iac.zip`;
  const href = `https://cloud.oracle.com/resourcemanager/stacks/create?zipUrl=${encodeURIComponent(archiveUrl)}`;

  return <a href={href}>{children}</a>;
}
