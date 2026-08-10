import React, {type ReactNode} from 'react';

import DocItemPaginator from '@theme-original/DocItem/Paginator';

export default function DocItemPaginatorWrapper(): ReactNode {
  return (
    <>
      <DocItemPaginator />
      <section className="doc-feedback">
        <h3>QUESTIONS? COMMENTS?</h3>
        <p>
          We’d love to hear from you!
          <br /> Contact us in the{' '}
          <a href="https://oracledevs.slack.com/archives/C089NPXG8AU">#ai-optimizer</a> channel in the{' '}
          <a href="https://oracledevs.slack.com">Oracle Developers Slack</a> workspace, or{' '}
          <a href="https://github.com/oracle/ai-optimizer/issues/new">open an issue in GitHub</a>.
        </p>
      </section>
    </>
  );
}
