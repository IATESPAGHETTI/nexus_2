import type { RecordingHeader } from "../../api/recordings";
import styles from "./RecordedBanner.module.css";

interface Props {
  header: RecordingHeader;
  shown: number;
  total: number;
  playing: boolean;
  onTogglePlay: () => void;
  onRestart: () => void;
  onShowAll: () => void;
}

export function RecordedBanner({ header, shown, total, playing, onTogglePlay, onRestart, onShowAll }: Props) {
  const when = header.recorded_at ? new Date(header.recorded_at).toLocaleString() : "unknown time";
  return (
    <div className={styles.banner} role="status">
      <div className={styles.text}>
        <span className={styles.tag}>Recorded run, not live</span>
        <p>
          A real investigation, recorded {when} with <code>{header.model}</code> ({header.arm}). Nothing is running
          now: the events below are played back from the saved record, unchanged. Fault: <code>{header.scenario}</code>,
          result: {header.outcome}.
        </p>
      </div>
      <div className={styles.controls}>
        <span className={styles.progress}>
          {shown} / {total} events
        </span>
        <button type="button" onClick={onTogglePlay} disabled={shown >= total}>
          {playing ? "Pause" : "Play"}
        </button>
        <button type="button" onClick={onRestart}>
          Restart
        </button>
        <button type="button" onClick={onShowAll} disabled={shown >= total}>
          Show all
        </button>
      </div>
    </div>
  );
}
