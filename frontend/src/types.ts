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
  effectiveGradePercent?: number | null;
  sentGradePercent?: number | null;
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
  files: string[];
};

export type Sample = {
  t: number;
  power: number | null;
  heart: number | null;
  cadence: number | null;
  speed: number | null;       // physics speed of the virtual road when there is one, else the trainer's
  grade: number | null;       // road grade (or, in old recordings, the ordered grade)
  effective?: number | null;  // grade the trainer applies (after difficulty), when it controls it
  distance?: number | null;   // km on the virtual road
  altitude?: number | null;   // m
};

export type Session = { durationSeconds: number; gradeKind: string; samples: Sample[] };

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
};

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
