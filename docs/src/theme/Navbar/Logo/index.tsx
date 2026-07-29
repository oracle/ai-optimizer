import React, {type ReactNode} from 'react';

import Link from '@docusaurus/Link';
import {useThemeConfig} from '@docusaurus/theme-common';
import useBaseUrl from '@docusaurus/useBaseUrl';
import ThemedImage from '@theme/ThemedImage';

export default function NavbarLogo(): ReactNode {
  const {
    navbar: {logo, title},
  } = useThemeConfig();
  const logoSource = logo?.src ?? '';
  const logoSources = {
    dark: useBaseUrl(logo?.srcDark || logoSource),
    light: useBaseUrl(logoSource),
  };
  const logoLink = useBaseUrl(logo?.href || '/');
  const oracleLogo = useBaseUrl('/img/oracle_logo.png');

  return (
    <Link
      className="navbar__brand"
      to={logoLink}
      {...(logo?.target && {target: logo.target})}>
      {logo && (
        <div className="navbar__logo">
          <ThemedImage
            alt=""
            className={logo.className}
            height={logo.height}
            sources={logoSources}
            style={logo.style}
            width={logo.width}
          />
        </div>
      )}
      {title && (
        <b className="navbar__title text--truncate">
          {title}
          <span className="navbar__title-powered-by">
            Powered by <img alt="Oracle" src={oracleLogo} />
          </span>
        </b>
      )}
    </Link>
  );
}
