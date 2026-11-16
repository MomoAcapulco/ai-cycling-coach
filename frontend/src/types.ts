/** Contract with the Python adapter (passed through untouched by the Java API). */

export type Mode = 'SIMULATOR' | 'WAHOO' | 'REPLAY';

export type Telemetry = {
  source: string;
  mode?: Mode;
  powerWatts: number;
  cadenceRpm: number;
  speedKph: number;
  elapsedSeconds: number;
  connected: boolean;
  status?: string;
  error?: string | null;
  heartRateBpm: number | null;
  heartRateConnected: boolean;
  heartRateStatus?: string;
  heartRateError?: string | null;
  targetGradePercent?: number | null;
  estimatedDistanceKm?: number | null;
  mechanicalWorkKj?: number | null;
  zwiftLeftConnected?: boolean;
  zwiftRightConnected?: boolean;
  zwiftLeftStatus?: string;
  zwiftRightStatus?: string;
  zwiftLeftBatteryPercent?: number | null;
  zwiftRightBatteryPercent?: number | null;
  virtualGear?: number;
  virtualGearCount?: number;
  virtualGearRelativeRatio?: number;
  gearControlMode?: 'DISPLAY_ONLY' | 'TRAINER';
  trainerGear?: number | null;
  trainerGearRatio?: number | null;
  requestedGear?: number;
  gearStatus?: string;
  gearLastRefusal?: string | null;
  gradeControlMode?: 'TRAINER' | 'SIMULATED' | null;
  roadGradePercent?: number | null;
  rideSpeedKph?: number | null;
  rideDistanceKm?: number | null;
  altitudeM?: number | null;
  elevationGainM?: number | null;
  vamMh?: number | null;
  wattsPerKg?: number | null;
  gradeTransitionMetersPerPercent?: number;
  ftpW?: number | null;           // the profile's FTP, or the one estimated from the history
  ftpSource?: 'profile' | 'history' | null;
  workoutType?: 'RAMP_TEST' | 'STRUCTURED';
  workoutPhase?: 'WARMUP' | 'RAMP' | 'RUNNING' | 'DONE' | 'ABORTED';
  workoutId?: string;
  workoutName?: string;
  workoutTotalS?: number;
  workoutBlock?: number | null;
  workoutBlockCount?: number;
  workoutBlockName?: string | null;
  workoutBlockKind?: BlockKind | null;
  targetCadenceRpm?: number | null;
  workoutNext?: { name: string; kind: BlockKind; seconds: number; targetW: number; cadence: number | null } | null;
  workoutFtpW?: number;
  workoutFtpSource?: string;
  workoutPlan?: WorkoutBlock[];
  workoutResults?: BlockResult[];
  workoutCompliancePct?: number | null;
  workoutRunning?: boolean;
  workoutElapsedS?: number;
  workoutStep?: number | null;
  workoutStepRemainingS?: number | null;
  targetPowerW?: number | null;
  workoutStartW?: number;
  workoutStepW?: number;
  rampBest60sW?: number | null;
  ftpEstimateW?: number | null;
  workoutEndReason?: string | null;
  rampMaxHeartRate?: number | null;
  routeFile?: string | null;
  routeName?: string | null;
  routeDistanceKm?: number | null;
  routeProgressKm?: number | null;
  routeFinished?: boolean | null;
  effectiveGradePercent?: number | null;
  sentGradePercent?: number | null;
  appliedGradePercent?: number | null;
  gradeConfirmed?: boolean;
  gradeStatus?: string;
  gradeDifficultyPercent?: number;
  gradeDescentFactorPercent?: number;
  gradeMinPercent?: number;
  gradeMaxPercent?: number;
  sessionState?: SessionState;
  session?: string | null;
  sessionElapsedSeconds?: number | null;
  sessionDistanceKm?: number | null;
  sessionWorkKj?: number | null;
  sessionElevationGainM?: number | null;
  sessionAvgPowerW?: number | null;
  lastButton?: string | null;
  controlStatus?: string;
  replayPlaying?: boolean;
  replaySpeed?: number;
  replayDurationSeconds?: number;
  replayFile?: string;
};

export type SessionState = 'IDLE' | 'RUNNING' | 'PAUSED' | 'UNAVAILABLE';

export type BlockKind = 'WARMUP' | 'WORK' | 'REST' | 'COOLDOWN';
export type WorkoutBlock = {
  name: string; kind: BlockKind; seconds: number; startPct: number; endPct: number; cadence: number | null;
  startW: number | null; endW: number | null;
};
export type BlockResult = {
  name: string; kind: BlockKind; seconds: number; plannedSeconds: number; avgW: number; targetW: number;
  compliancePct: number | null; inRangePct: number;
};
export type WorkoutInfo = {
  id: string; name: string; goal: string; seconds: number; workSeconds: number; intensityFactor: number; tss: number;
  blocks: WorkoutBlock[];
};
export type WorkoutLibrary = { ftpW: number | null; ftpSource: 'profile' | 'history' | null; workouts: WorkoutInfo[] };
export type SessionWorkout = {
  type: 'STRUCTURED' | 'RAMP_TEST'; name: string; endReason: string | null; ftpW: number | null;
  completedPct?: number; workCompliancePct?: number | null; workInRangePct?: number | null; blocks?: BlockResult[];
  best60sW?: number | null;
};

export type GeneratedRoute = RouteSummary & { seed: number; profile: { d: number; e: number; g: number }[]; saved: boolean };

export type FtpEstimate = {
  ftp: number; method: 'cp' | 'single'; seconds: number | null; cp: number | null; wPrime: number | null;
  modelFtp: number | null; singleFtp: number | null;
  efforts: { seconds: number; w: number; id: string; date: string; name: string | null }[];
};
export type FtpAdvice = {
  ftp: number | null; kind: 'raise' | 'set' | 'test' | 'ok'; reason: 'above' | 'no_ftp' | 'no_max_effort' | 'falling' | 'ok';
  suggestedFtp: number | null; estimateFtp: number | null; estimateFrom: 'indoor' | 'outdoor' | null;
  indoor: FtpEstimate | null; outdoor: FtpEstimate | null;
  lastMaxEffort: { date: string; name: string | null; daysAgo: number } | null; lastTest: { date: string } | null;
  windowDays: number; maxEffortDays: number;
};

export type SessionSummary = {
  session: string;
  startedAtUtc: string;
  finishedAtUtc: string;
  finishReason: string;
  csv: string;
  rawCapture: string | null;
  elapsedSeconds: number;
  movingSeconds: number;
  distanceKm: number;
  workKj: number;
  avgPowerW: number | null;
  avgMovingPowerW: number | null;
  maxPowerW: number | null;
  avgCadenceRpm: number | null;
  avgHeartRateBpm: number | null;
  maxHeartRateBpm: number | null;
  normalizedPowerW: number | null;
  ftpWatts: number | null;
  intensityFactor: number | null;
  tss: number | null;
  gearSeconds: Record<string, number>;
  avgSpeedKph?: number | null;
  elevationGainM?: number;
  climbSeconds?: number;
  vamMh?: number | null;
  riderWeightKg?: number | null;
  avgWattsPerKg?: number | null;
  bestEffortsW?: Record<string, number | null>;
  best20MinWattsPerKg?: number | null;
  estimatedFtpW?: number | null;
  workout?: SessionWorkout;
  feedback?: SessionFeedback;
  routes?: { file: string; name: string | null; km: number }[];
  files: string[];
};

export type Sample = {
  t: number;
  power: number | null;
  target?: number | null;     // the workout's power target, when there is one
  heart: number | null;
  cadence: number | null;
  speed: number | null;       // physics speed of the virtual road when there is one, else the trainer's
  grade: number | null;       // road grade (or, in old recordings, the ordered grade)
  effective?: number | null;  // grade the trainer applies (after difficulty), when it controls it
  distance?: number | null;   // km on the virtual road
  altitude?: number | null;   // m
};

export type Session = { durationSeconds: number; gradeKind: string; samples: Sample[]; routes?: { file: string; name: string | null; km: number }[] };
export type RouteRide = {
  session: string; date: string | null; km: number | null; seconds: number; csv: string | null;
  replayable: boolean; why: string | null; rpe: number | null;
};

export type Settings = {
  mode: Mode;
  replayFile: string | null;
  hrEnabled: boolean;
  zwiftEnabled: boolean;
  recordEnabled: boolean;
  recordSeconds: number;
  gearControlEnabled: boolean;
};

export type AdminState = {
  settings: Settings;
  source: 'env' | 'saved';
  envDefaults: Settings;
  settingsFile: string | null;
  controlTestEnabled: boolean;
  recordingsDir: string;
  modes: Mode[];
};

export type Drivetrain = 'ZWIFT_COG' | 'CASSETTE';

export type RiderProfile = {
  riderWeightKg: number;
  bikeWeightKg: number;
  ftpWatts: number | null;
  drivetrain: Drivetrain;
  totalMassKg?: number;
  gradeDifficultyPercent: number;
  gradeDescentFactorPercent: number;
  maxGradePercent: number;
  minGradePercent: number;
  gradeTransitionMetersPerPercent: number;
  bikeType: BikeType;
  restingHeartRate?: number | null;
  maxHeartRate?: number | null;
  thresholdHeartRate?: number | null;
};

export type BikeType = 'ROAD' | 'MTB';

export type ProfileState = { profile: RiderProfile; saved: boolean; profileFile: string };

export type Recording = {
  name: string;
  path: string;
  sizeBytes: number;
  modifiedUtc: string;
  valid: boolean;
  samples: number | null;
  durationSeconds: number | null;
  error: string | null;
};

export type RememberedDevice = {
  address: string;
  name: string | null;
  kind: string;
  zwiftModel: string | null;
  zwiftType: number | null;
  sideConfirmedByButton: boolean;
  rememberedAtUtc: string;
  lastUsedAtUtc?: string | null;
  preferred?: boolean;
};

export type RouteSummary = {
  file: string;
  name: string;
  valid: boolean;
  error: string | null;
  distanceKm?: number;
  elevationGainM?: number;
  elevationLossM?: number;
  maxGradePercent?: number;
  minGradePercent?: number;
  clippedSteps?: number;
  points?: number;
  thumb?: { d: number; e: number; g: number }[];
  generated?: boolean;          // made in Rutas → Generar
  recorded?: boolean;           // a recorded ride (times on its points): it has its own replay
  gpxName?: string;             // the name inside the GPX (``name`` may be the rider's own)
  rides?: number;               // sessions ridden on it
  lastRide?: RouteRide | null;
  replayRide?: RouteRide | null; // the newest session on it that has enough data to replay
};
export type SessionFeedback = { rpe: number | null; note: string | null; updatedUtc?: string };

/** The route being ridden: summary plus the profile for the chart (d km, e m, g % of the next step). */
export type ActiveRoute = { active: false } | (RouteSummary & {
  active: true; progressKm: number; finished: boolean; profile: { d: number; e: number; g: number }[];
});

export type ActivityType = 'ride' | 'virtual_ride' | 'run' | 'strength' | 'workout' | 'other';

export type Activity = {
  id: string; source: 'app' | 'strava' | string; start_utc: string | null; type: ActivityType; name: string | null;
  rpe?: number | null; feeling?: string | null;
  elapsed_s: number | null; moving_s: number | null; distance_m: number | null; ascent_m: number | null;
  avg_power: number | null; max_power: number | null; np: number | null; work_kj: number | null;
  avg_hr: number | null; max_hr: number | null; avg_cadence: number | null; has_power: number; has_hr: number;
  device: string | null; strava_relative_effort: number | null;
};

export type HistoryWeek = {
  week: string; hours: Partial<Record<ActivityType, number>>; activities: number; distanceKm: number; ascentM: number; workKj: number;
};

export type LoadDay = { date: string; tss: number; ctl: number; atl: number; tsb: number };

export type LoadReport = {
  params: {
    ftp: number | null; ftp_source: 'profile' | 'history' | null; hr_rest: number; hr_rest_source: 'profile' | 'default';
    hr_max: number | null; hr_max_source: 'profile' | 'history' | null; lthr: number | null; lthr_source: 'profile' | 'estimate' | null;
  };
  today: { ctl: number; atl: number; tsb: number; ctlChange7d: number | null };
  days: LoadDay[];
  activities: { id: string; tss: number; method: 'power' | 'hr' | 'hr_avg' | 'estimate'; duplicateOf: string | null }[];
  methods: Record<string, number>;
  duplicates: number;
};

export type DeviceRole = 'trainer' | 'heart_rate' | 'zwift_left' | 'zwift_right';

export type DeviceCandidate = { address: string; name: string | null; rssi: number | null };

export type DevicesState = {
  registryFile: string | null;
  /** The device chosen first for each role (kept for compatibility). */
  remembered: Partial<Record<DeviceRole, RememberedDevice>>;
  /** Every known device per role, the one chosen first at the top. */
  known?: Partial<Record<DeviceRole, RememberedDevice[]>>;
  /** Several unknown devices nearby and no known one: waiting for the rider's choice. */
  pending?: Partial<Record<DeviceRole, DeviceCandidate[]>>;
  envFilters?: Partial<Record<DeviceRole, { id: string | null }>>;
};
