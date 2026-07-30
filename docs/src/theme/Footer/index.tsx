import React, {type ReactNode} from 'react';

import {useThemeConfig} from '@docusaurus/theme-common';

function Footer(): ReactNode {
  const {footer} = useThemeConfig();

  return (
    <footer className="footer footer--dark">
      <div className="container container-fluid">
        {footer?.copyright && (
          <div className="footer__bottom text--center">
            <div className="footer__copyright">{footer.copyright}</div>
          </div>
        )}
      </div>
    </footer>
  );
}

export default React.memo(Footer);
