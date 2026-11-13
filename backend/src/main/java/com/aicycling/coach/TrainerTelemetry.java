package com.aicycling.coach;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

/**
 * Telemetry fields as of v4.2.2. Since v4.3.0 {@link TrainerController} passes the adapter's JSON through
 * instead of deserialising into this record (which silently dropped undeclared fields such as
 * cyclingPowerWatts). Kept as a reference of the contract; it is not on the request path.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record TrainerTelemetry(
        String source,
        int powerWatts,
        double cadenceRpm,
        double speedKph,
        long elapsedSeconds,
        boolean connected,
        String status,
        Double lastUpdateSeconds,
        String error,
        Integer heartRateBpm,
        boolean heartRateConnected,
        String heartRateStatus,
        Double heartRateLastUpdateSeconds,
        String heartRateError,
        Double targetGradePercent,
        Double gradePercent,
        Double estimatedDistanceKm,
        Double mechanicalWorkKj,
        String controlStatus,
        String experimentPhase,
        Boolean zwiftLeftConnected,
        Boolean zwiftRightConnected,
        String zwiftLeftStatus,
        String zwiftRightStatus,
        Integer virtualGear,
        Integer virtualGearCount,
        String lastButton,
        String lastButtonSide,
        Integer buttonPressCount,
        String gearControlMode,
        Double virtualGearRelativeRatio,
        Boolean replayPlaying,
        Double replaySpeed,
        Double replayDurationSeconds) {}
