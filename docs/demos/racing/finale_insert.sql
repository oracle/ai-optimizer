-- Racing demo final reveal
-- Run this only at the final reveal, after the audience has seen that
-- Round 6 team points are absent from the bootstrap database.

ALTER SESSION SET NLS_DATE_FORMAT = 'YYYY-MM-DD';

MERGE INTO team_race_points target
USING (
  SELECT
    r.race_id,
    t.team_id,
    v.points,
    'Final after post-race checks' AS publication_status,
    v.race_control_note
  FROM races r
  CROSS JOIN (
    SELECT 'Nova Circuit' AS team_name, 95 AS points, 'Strong final stint and clean pit execution' AS race_control_note FROM dual
    UNION ALL SELECT 'Phoenix Racing Lab', 92, 'Fastest average pit work; minor track-limits warning reviewed with no team penalty' FROM dual
    UNION ALL SELECT 'Vertex GP', 89, 'Consistent top-ten finishes across both race simulations' FROM dual
    UNION ALL SELECT 'Apex Dynamics', 86, 'Good qualifying pace with moderate tyre degradation' FROM dual
    UNION ALL SELECT 'Carbon Shift', 83, 'High top speed; lost points after late-race contact' FROM dual
    UNION ALL SELECT 'Quantum Apex', 80, 'Efficient energy deployment over the final stint' FROM dual
    UNION ALL SELECT 'Velocity Forge', 77, 'Reliable finish with limited overtaking opportunities' FROM dual
    UNION ALL SELECT 'Blue Torque', 74, 'Conservative strategy reduced retirement risk' FROM dual
    UNION ALL SELECT 'Delta Velocity', 71, 'Dry-race pace reduced by a wet-setup compromise' FROM dual
    UNION ALL SELECT 'Titan Motorsport', 68, 'Mechanical checks extended two pit stops' FROM dual
    UNION ALL SELECT 'Solstice Motorsport', 65, 'Mid-pack rhythm; lost ground after a slow first pit window' FROM dual
    UNION ALL SELECT 'Helix Engineering', 62, 'Steady race pace; missed an undercut opportunity' FROM dual
    UNION ALL SELECT 'Orbit Performance', 59, 'Two clean stints offset by a late-race vibration check' FROM dual
    UNION ALL SELECT 'Catalyst Racing', 56, 'Aggressive opening lap paid off; tyre deg limited the second stint' FROM dual
    UNION ALL SELECT 'Strata GP', 53, 'Cautious tyre strategy traded position for finish reliability' FROM dual
    UNION ALL SELECT 'Pulse Velocity', 50, 'Recovery drive after early contact; salvaged minor points' FROM dual
    UNION ALL SELECT 'Halo Speedworks', 47, 'Brake balance drift cost lap time through the middle stint' FROM dual
    UNION ALL SELECT 'Equinox Racing', 44, 'Wet-setup compromise hurt dry-line pace' FROM dual
    UNION ALL SELECT 'Synapse Motorsport', 41, 'Energy deployment timing flagged for review' FROM dual
    UNION ALL SELECT 'Forge Edge Racing', 38, 'Reliability concerns required a precautionary long stop' FROM dual
  ) v
  JOIN teams t ON t.team_name = v.team_name
  WHERE r.race_name = 'Round 6: Finale Preview'
) source
ON (
  target.race_id = source.race_id
  AND target.team_id = source.team_id
)
WHEN MATCHED THEN UPDATE SET
  target.points = source.points,
  target.publication_status = source.publication_status,
  target.race_control_note = source.race_control_note,
  target.recorded_at = SYSTIMESTAMP
WHEN NOT MATCHED THEN INSERT (
  race_id,
  team_id,
  points,
  publication_status,
  race_control_note
) VALUES (
  source.race_id,
  source.team_id,
  source.points,
  source.publication_status,
  source.race_control_note
);

COMMIT;

-- SELECT
--   team_name,
--   pre_finale_points,
--   round6_points,
--   final_total_points,
--   round6_status
-- FROM championship_team_standings
-- ORDER BY final_total_points DESC;
