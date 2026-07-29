import type {ReactNode} from 'react';
import clsx from 'clsx';
import Heading from '@theme/Heading';
import styles from './styles.module.css';

type FeatureItem = {
  title: string;
  Svg: React.ComponentType<React.ComponentProps<'svg'>>;
  description: ReactNode;
};

const FeatureList: FeatureItem[] = [
  {
    title: 'Build with Familiar Tools',
    Svg: require('@site/static/img/build_with_familiar_tools.svg').default,
    description: (
      <>
        Build GenAI applications using Oracle AI Database and your existing open-source tools while keeping your private enterprise data in place.
      </>
    ),
  },
  {
    title: 'Ground Models in Your Data',
    Svg: require('@site/static/img/ground_models_in_your_data.svg').default,
    description: (
      <>
        Reduce hallucinations and enrich model knowledge with your structured and unstructured data using retrieval-augmented generation (RAG) and natural language to SQL (NL2SQL).
      </>
    ),
  },
  {
    title: 'Test and Refine AI Solutions',
    Svg: require('@site/static/img/test_and_refine_ai_solutions.svg').default,
    description: (
      <>
          Configure models, tune prompts and parameters, prepare embeddings, and evaluate results in a single iterative workflow.
      </>
    ),
  },
];

function Feature({title, Svg, description}: FeatureItem) {
  return (
    <div className={clsx('col col--4')}>
      <div className="text--center">
        <Svg className={styles.featureSvg} role="img" />
      </div>
      <div className="text--center padding-horiz--md">
        <Heading as="h3">{title}</Heading>
        <p>{description}</p>
      </div>
    </div>
  );
}

export default function HomepageFeatures(): ReactNode {
  return (
    <section className={styles.features}>
      <div className="container">
        <div className="row">
          {FeatureList.map((props, idx) => (
            <Feature key={idx} {...props} />
          ))}
        </div>
      </div>
    </section>
  );
}
