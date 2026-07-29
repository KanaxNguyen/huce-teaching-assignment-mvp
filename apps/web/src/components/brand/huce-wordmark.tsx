import React from "react";
import styles from "./huce-wordmark.module.css";

export function HuceWordmark({ compact = false }: { compact?: boolean }) {
  return (
    <div className={styles.wordmark} aria-label="HUCE Teaching Assignment">
      <span className={styles.wordmarkMark}>H</span>
      {!compact && (
        <span className={styles.wordmarkCopy}>
          <strong>HUCE</strong>
          <small>Teaching Assignment</small>
        </span>
      )}
    </div>
  );
}
