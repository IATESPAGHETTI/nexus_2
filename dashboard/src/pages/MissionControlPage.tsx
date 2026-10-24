import { useHashScroll } from "../lib/useHashScroll";
import { HeroPinned } from "../components/story/HeroPinned";
import { FinalCta, TechMarquee } from "../components/story/StorySections";
import { LiveBand } from "../components/story/LiveBand";
import { RecentIncidents } from "../components/story/RecentIncidents";
import styles from "../components/story/Story.module.css";

const goLive = () => document.getElementById("pl-live")?.scrollIntoView({ behavior: "smooth" });

/** Mission Control (the home page, linked as "Mission Control" in the top navigation): the same design system as /presentation, minus the long-form story. */
export function MissionControlPage() {
  useHashScroll();
  return (
    <div className={styles.page}>
      <HeroPinned onDemoClick={goLive} />
      <TechMarquee />
      <LiveBand withPipeline={false} />
      <RecentIncidents />
      <FinalCta onClick={goLive} />
    </div>
  );
}
