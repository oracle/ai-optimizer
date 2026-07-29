import React, {type ReactNode} from 'react';
import clsx from 'clsx';

import {useVisitedDocs} from '@site/src/components/VisitedDocs';
import DocSidebarItemLink from '@theme-original/DocSidebarItem/Link';
import type {Props} from '@theme/DocSidebarItem/Link';

export default function DocSidebarItemLinkWrapper(props: Props): ReactNode {
  const {hasVisitedDoc} = useVisitedDocs();
  const {item} = props;
  const visitedItem = hasVisitedDoc(item.href)
    ? {...item, className: clsx(item.className, 'doc-sidebar-item--visited')}
    : item;

  return <DocSidebarItemLink {...props} item={visitedItem} />;
}
