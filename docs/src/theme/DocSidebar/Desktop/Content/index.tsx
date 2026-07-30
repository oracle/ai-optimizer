import React, {type ReactNode} from 'react';

import GithubButtons from '@site/src/components/GithubButtons';
import {useVisitedDocs} from '@site/src/components/VisitedDocs';
import DocSidebarDesktopContent from '@theme-original/DocSidebar/Desktop/Content';
import type {Props} from '@theme/DocSidebar/Desktop/Content';

export default function DocSidebarDesktopContentWrapper(
  props: Props,
): ReactNode {
  const {clearVisitedDocs, hasVisitedDocs} = useVisitedDocs();

  return (
    <>
      <DocSidebarDesktopContent {...props} />
      <div className="doc-sidebar-history">
        <button
          className="clean-btn doc-sidebar-history__clear"
          disabled={!hasVisitedDocs}
          onClick={clearVisitedDocs}
          type="button">
          ♽ Clear History
        </button>
      </div>
      <GithubButtons />
    </>
  );
}
