import React, {type ReactNode} from 'react';

import {VisitedDocsProvider} from '@site/src/components/VisitedDocs';

export default function Root({children}: {children: ReactNode}): ReactNode {
  return <VisitedDocsProvider>{children}</VisitedDocsProvider>;
}
