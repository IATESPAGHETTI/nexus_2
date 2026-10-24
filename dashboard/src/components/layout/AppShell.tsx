import { PropsWithChildren, useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import { AgentMasterToggle } from "../common/AgentMasterToggle";
import { useAgentControl } from "../../context/AgentControlContext";
import { Sidebar } from "./Sidebar";
import styles from "./AppShell.module.css";

/** Announcement strip (the reference has one above its nav). Real state only. */
function StatusStrip() {
  const { agentsEnabled, backendReachable, demoStatus, isLoading } = useAgentControl();
  let tone = styles.stripIdle;
  let text = "Agents are OFF. Nothing on this page is live.";
  let link: { to: string; label: string } | null = { to: "/presentation#pl-live", label: "Turn them on" };

  if (agentsEnabled && isLoading) {
    text = "Connecting to the NEXUS backend…";
    link = null;
  } else if (agentsEnabled && !backendReachable) {
    tone = styles.stripWarn;
    text = "Backend unreachable. No data is shown.";
    link = null;
  } else if (agentsEnabled) {
    tone = styles.stripLive;
    text = `Live: ${demoStatus?.agents_reachable_count ?? 0} of ${demoStatus?.agents_total ?? 7} agent services reachable.`;
    link = { to: "/presentation#pl-live", label: "Open the command center" };
  }

  return (
    <div className={`${styles.strip} ${tone}`}>
      <span className={styles.stripDot} />
      <span>{text}</span>
      {link && (
        <Link to={link.to} className={styles.stripLink}>
          {link.label} →
        </Link>
      )}
    </div>
  );
}

export function AppShell({ children }: PropsWithChildren) {
  const { pathname, hash } = useLocation();
  const marketing = pathname === "/" || pathname === "/presentation";
  const isIncidentView = pathname.startsWith("/incidents/");
  const lightPage = marketing || isIncidentView;   // every page is light now; the incident view reuses the light tokens

  useEffect(() => {
    document.body.classList.toggle("nx-body-light", lightPage);
    return () => document.body.classList.remove("nx-body-light");
  }, [lightPage]);

  const item = (active: boolean) => `${styles.navItem} ${active ? styles.navItemActive : ""}`;

  return (
    <div className={`${styles.shell} ${lightPage ? "nx-light" : ""}`}>
      <header className={`${styles.topNav} ${lightPage ? styles.light : styles.dark}`}>
        <StatusStrip />
        <div className={styles.navMain}>
          <div className={styles.navContainer}>
            <Link to="/" className={styles.brandLink}>
              <span className={styles.brandMark} aria-hidden="true" />
              <span className={styles.brandWordmark}>NEXUS</span>
            </Link>

            <nav className={styles.navLinks}>
              <Link to="/" className={item(pathname === "/" && !hash)}>
                Mission Control
              </Link>
              <Link to="/#recent-incidents" className={item(pathname === "/" && hash === "#recent-incidents")}>
                Incidents
              </Link>
              <Link to="/presentation#pl-agents" className={item(pathname === "/presentation" && hash === "#pl-agents")}>
                Agents
              </Link>
              <Link to="/presentation" className={item(pathname === "/presentation" && hash !== "#pl-agents")}>
                Presentation
              </Link>
            </nav>

            <div className={styles.navRight}>
              <div className={styles.toggleChip}>
                <AgentMasterToggle compact />
              </div>
              <Link to="/presentation#pl-live" className={styles.navCta}>
                Run the demo
              </Link>
            </div>
          </div>
        </div>
      </header>

      <div className={styles.contentLayout}>
        {isIncidentView && (
          <aside className={styles.sidebarWrapper}>
            <Sidebar />
          </aside>
        )}
        <main className={styles.main}>{children}</main>
      </div>
    </div>
  );
}
