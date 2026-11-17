package com.aicycling.coach;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/** The Java API against a fake Python adapter on a free local port. */
@SpringBootTest
@AutoConfigureMockMvc
class TrainerControllerTest {

    /** What the fake adapter answers per path: status and body. */
    record Reply(int status, String body) {}

    static final Map<String, Reply> REPLIES = new ConcurrentHashMap<>();
    static final Map<String, String> LAST_REQUEST = new ConcurrentHashMap<>();
    static final HttpServer ADAPTER = startAdapter();

    @Autowired
    MockMvc mvc;

    @DynamicPropertySource
    static void adapterUrl(DynamicPropertyRegistry registry) {
        registry.add("trainer.adapter.url", () -> "http://127.0.0.1:" + ADAPTER.getAddress().getPort());
    }

    static HttpServer startAdapter() {
        try {
            HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
            server.createContext("/", TrainerControllerTest::answer);
            server.start();
            return server;
        } catch (IOException ex) {
            throw new IllegalStateException(ex);
        }
    }

    static void answer(HttpExchange exchange) throws IOException {
        String path = exchange.getRequestURI().getPath();
        LAST_REQUEST.put("method", exchange.getRequestMethod());
        LAST_REQUEST.put("path", path);
        LAST_REQUEST.put("query", String.valueOf(exchange.getRequestURI().getRawQuery()));
        LAST_REQUEST.put("contentType", String.valueOf(exchange.getRequestHeaders().getFirst("Content-Type")));
        LAST_REQUEST.put("contentLength", String.valueOf(exchange.getRequestHeaders().getFirst("Content-Length")));
        LAST_REQUEST.put("transferEncoding", String.valueOf(exchange.getRequestHeaders().getFirst("Transfer-Encoding")));
        LAST_REQUEST.put("body", new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
        Reply reply = REPLIES.getOrDefault(path, new Reply(404, "<html>Not Found</html>"));
        byte[] bytes = reply.body().getBytes(StandardCharsets.UTF_8);
        exchange.sendResponseHeaders(reply.status(), bytes.length == 0 ? -1 : bytes.length);
        if (bytes.length > 0) {
            exchange.getResponseBody().write(bytes);
        }
        exchange.close();
    }

    @AfterAll
    static void stopAdapter() {
        ADAPTER.stop(0);
    }

    @BeforeEach
    void reset() {
        REPLIES.clear();
        LAST_REQUEST.clear();
    }

    @Test
    void telemetryIsPassedThroughWithEveryField() throws Exception {
        REPLIES.put("/telemetry", new Reply(200,
                "{\"source\":\"WAHOO\",\"powerWatts\":180,\"cyclingPowerWatts\":182,"
                        + "\"averagePowerWatts\":170,\"heartRateBpm\":null,\"brandNewField\":\"kept\"}"));
        mvc.perform(get("/api/trainer/telemetry"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.powerWatts").value(180))
                .andExpect(jsonPath("$.cyclingPowerWatts").value(182))
                .andExpect(jsonPath("$.averagePowerWatts").value(170))
                .andExpect(jsonPath("$.brandNewField").value("kept"))
                .andExpect(jsonPath("$.heartRateBpm").isEmpty());
    }

    @Test
    void adapterConflictStaysAConflict() throws Exception {
        REPLIES.put("/replay/session", new Reply(409, "Only available in REPLAY mode"));
        mvc.perform(get("/api/trainer/replay/session"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.adapterStatus").value(409))
                .andExpect(jsonPath("$.error").value("Trainer adapter rejected request"));
    }

    @Test
    void adapterBadRequestStaysABadRequest() throws Exception {
        REPLIES.put("/replay/gear", new Reply(400, "delta must be integer"));
        mvc.perform(post("/api/trainer/replay/gear").contentType(MediaType.APPLICATION_JSON).content("{\"delta\":\"up\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.adapterStatus").value(400));
    }

    @Test
    void postIsForwardedWithContentLengthAndNotChunked() throws Exception {
        REPLIES.put("/replay/control", new Reply(200, "{\"positionSeconds\":300.0,\"playing\":false}"));
        mvc.perform(post("/api/trainer/replay/control").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"action\":\"seek\",\"value\":300}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.positionSeconds").value(300.0));
        assertThat(LAST_REQUEST.get("method")).isEqualTo("POST");
        assertThat(LAST_REQUEST.get("path")).isEqualTo("/replay/control");
        assertThat(LAST_REQUEST.get("transferEncoding")).isEqualTo("null");
        assertThat(Integer.parseInt(LAST_REQUEST.get("contentLength")))
                .isEqualTo(LAST_REQUEST.get("body").getBytes(StandardCharsets.UTF_8).length);
        assertThat(LAST_REQUEST.get("body")).contains("\"action\":\"seek\"").contains("\"value\":300");
    }

    @Test
    void replayStateIsForwarded() throws Exception {
        REPLIES.put("/replay/state", new Reply(200, "{\"positionSeconds\":12.5}"));
        mvc.perform(get("/api/trainer/replay/state"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.positionSeconds").value(12.5));
    }

    @Test
    void devicesAreForwarded() throws Exception {
        REPLIES.put("/devices", new Reply(200, "{\"remembered\":{\"trainer\":{\"address\":\"K\"}}}"));
        mvc.perform(get("/api/trainer/devices"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.remembered.trainer.address").value("K"));
    }

    @Test
    void adminSettingsPostIsForwarded() throws Exception {
        REPLIES.put("/admin/settings", new Reply(200, "{\"source\":\"saved\"}"));
        mvc.perform(post("/api/trainer/admin/settings").contentType(MediaType.APPLICATION_JSON).content("{\"mode\":\"REPLAY\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.source").value("saved"));
        assertThat(LAST_REQUEST.get("path")).isEqualTo("/admin/settings");
        assertThat(LAST_REQUEST.get("body")).isEqualTo("{\"mode\":\"REPLAY\"}");
    }

    @Test
    void recordingUploadKeepsQueryAndBody() throws Exception {
        REPLIES.put("/admin/recordings", new Reply(201, "{\"name\":\"ride.csv\"}"));
        mvc.perform(post("/api/trainer/admin/recordings?name=ride.csv").contentType("text/csv").content("a,b\n1,2\n"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.name").value("ride.csv"));
        assertThat(LAST_REQUEST.get("query")).isEqualTo("name=ride.csv");
        assertThat(LAST_REQUEST.get("contentType")).isEqualTo("text/csv");
        assertThat(LAST_REQUEST.get("body")).isEqualTo("a,b\n1,2\n");
    }

    @Test
    void raceCalendarIsForwarded() throws Exception {
        REPLIES.put("/calendar", new Reply(200, "{\"month\":\"2026-11\"}"));
        mvc.perform(get("/api/trainer/calendar?month=2026-11"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.month").value("2026-11"));
        assertThat(LAST_REQUEST.get("query")).isEqualTo("month=2026-11");
        String id = "fa4e0000-0000-4000-8000-000000000001";   // a fake id (scripts/mask_personal_data.py)
        REPLIES.put("/goals/" + id + "/result", new Reply(200, "{\"id\":\"" + id + "\"}"));
        mvc.perform(post("/api/trainer/goals/" + id + "/result").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"finished\":true}"))
                .andExpect(status().isOk());
        assertThat(LAST_REQUEST.get("path")).isEqualTo("/goals/" + id + "/result");
        assertThat(LAST_REQUEST.get("body")).isEqualTo("{\"finished\":true}");
    }

    @Test
    void deviceForgetIsForwardedAsDelete() throws Exception {
        REPLIES.put("/devices/zwift_left", new Reply(200, "{\"forgotten\":\"zwift_left\"}"));
        mvc.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete("/api/trainer/devices/zwift_left"))
                .andExpect(status().isOk());
        assertThat(LAST_REQUEST.get("method")).isEqualTo("DELETE");
    }

    @Test
    void gearIsForwardedAndConflictKept() throws Exception {
        REPLIES.put("/gear", new Reply(409, "Shifting needs REPLAY or gear control on the trainer"));
        mvc.perform(post("/api/trainer/gear").contentType(MediaType.APPLICATION_JSON).content("{\"delta\":1}"))
                .andExpect(status().isConflict());
        assertThat(LAST_REQUEST.get("body")).isEqualTo("{\"delta\":1}");
    }

    @Test
    void gradeIsForwardedWithTheAdapterStatus() throws Exception {
        REPLIES.put("/grade", new Reply(200, "{\"targetGradePercent\":6.0,\"effectiveGradePercent\":3.0}"));
        mvc.perform(post("/api/trainer/grade").contentType(MediaType.APPLICATION_JSON).content("{\"gradePercent\":6}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.effectiveGradePercent").value(3.0));
        assertThat(LAST_REQUEST.get("body")).isEqualTo("{\"gradePercent\":6}");
        REPLIES.put("/grade", new Reply(409, "Grade control needs the real trainer with gear control on"));
        mvc.perform(post("/api/trainer/grade").contentType(MediaType.APPLICATION_JSON).content("{\"gradePercent\":2}"))
                .andExpect(status().isConflict());
        REPLIES.put("/grade", new Reply(400, "gradePercent must be between -15 and 20"));
        mvc.perform(post("/api/trainer/grade").contentType(MediaType.APPLICATION_JSON).content("{\"gradePercent\":30}"))
                .andExpect(status().isBadRequest());
    }

    @Test
    void rampTestIsForwarded() throws Exception {
        REPLIES.put("/workout/ramp/start", new Reply(200, "{\"workoutPhase\":\"WARMUP\"}"));
        mvc.perform(post("/api/trainer/workout/ramp/start"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.workoutPhase").value("WARMUP"));
        REPLIES.put("/workout/ftp/save", new Reply(409, "There is no FTP result to save"));
        mvc.perform(post("/api/trainer/workout/ftp/save")).andExpect(status().isConflict());
    }

    @Test
    void feedbackAndDeletionAreForwarded() throws Exception {
        REPLIES.put("/sessions/session_20261116_100000/feedback", new Reply(200, "{\"rpe\":7}"));
        mvc.perform(post("/api/trainer/sessions/session_20261116_100000/feedback").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"rpe\":7}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.rpe").value(7));
        REPLIES.put("/sessions/session_20261116_100000", new Reply(200, "{\"deleted\":\"session_20261116_100000\"}"));
        mvc.perform(delete("/api/trainer/sessions/session_20261116_100000"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.deleted").value("session_20261116_100000"));
        REPLIES.put("/routes/mine.gpx", new Reply(200, "{\"deleted\":\"mine.gpx\"}"));
        mvc.perform(delete("/api/trainer/routes/mine.gpx")).andExpect(status().isOk());
        REPLIES.put("/routes/mine.gpx/replay", new Reply(409, "Datos insuficientes"));
        mvc.perform(post("/api/trainer/routes/mine.gpx/replay")).andExpect(status().isConflict());
    }

    @Test
    void structuredWorkoutsAreForwarded() throws Exception {
        REPLIES.put("/workout/library", new Reply(200, "{\"ftpW\":200,\"workouts\":[{\"id\":\"vo2-5x4\"}]}"));
        mvc.perform(get("/api/trainer/workout/library"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.workouts[0].id").value("vo2-5x4"));
        REPLIES.put("/workout/structured/start", new Reply(200, "{\"workoutType\":\"STRUCTURED\"}"));
        mvc.perform(post("/api/trainer/workout/structured/start").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"id\":\"vo2-5x4\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.workoutType").value("STRUCTURED"));
    }

    @Test
    void historyIsForwarded() throws Exception {
        REPLIES.put("/history/weeks", new Reply(200, "{\"weeks\":[{\"week\":\"2026-11-09\"}]}"));
        mvc.perform(get("/api/trainer/history/weeks"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.weeks[0].week").value("2026-11-09"));
        REPLIES.put("/history", new Reply(200, "{\"activities\":[]}"));
        mvc.perform(get("/api/trainer/history")).andExpect(status().isOk());
    }

    @Test
    void gpxRoutesAreForwarded() throws Exception {
        REPLIES.put("/routes", new Reply(201, "{\"file\":\"climb.gpx\"}"));
        mvc.perform(post("/api/trainer/routes?name=climb.gpx").contentType("application/gpx+xml").content("<gpx/>"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.file").value("climb.gpx"));
        assertThat(LAST_REQUEST.get("query")).isEqualTo("name=climb.gpx");
        assertThat(LAST_REQUEST.get("contentType")).isEqualTo("application/gpx+xml");
        assertThat(LAST_REQUEST.get("body")).isEqualTo("<gpx/>");
        REPLIES.put("/route/start", new Reply(409, "Grade control needs the simulator"));
        mvc.perform(post("/api/trainer/route/start").contentType(MediaType.APPLICATION_JSON).content("{\"file\":\"climb.gpx\"}"))
                .andExpect(status().isConflict());
        REPLIES.put("/route", new Reply(200, "{\"active\":false}"));
        mvc.perform(get("/api/trainer/route")).andExpect(status().isOk()).andExpect(jsonPath("$.active").value(false));
    }

    @Test
    void sessionActionsAndListAreForwarded() throws Exception {
        REPLIES.put("/session/start", new Reply(200, "{\"sessionState\":\"RUNNING\"}"));
        mvc.perform(post("/api/trainer/session/start"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.sessionState").value("RUNNING"));
        REPLIES.put("/sessions", new Reply(200, "{\"sessions\":[]}"));
        mvc.perform(get("/api/trainer/sessions")).andExpect(status().isOk());
    }

    @Test
    void sessionFileIsPassedThroughAsBytes() throws Exception {
        REPLIES.put("/sessions/session_20261112_160000.csv", new Reply(200, "recordedAtUtc,elapsedSeconds\n"));
        mvc.perform(get("/api/trainer/sessions/session_20261112_160000.csv"))
                .andExpect(status().isOk())
                .andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.content()
                        .string("recordedAtUtc,elapsedSeconds\n"));
        mvc.perform(get("/api/trainer/sessions/session_20990101_000000.csv")).andExpect(status().isNotFound());
    }

    @Test
    void emptyAdapterResponseIsABadGateway() throws Exception {
        REPLIES.put("/telemetry", new Reply(200, ""));
        mvc.perform(get("/api/trainer/telemetry")).andExpect(status().isBadGateway());
    }

    @Test
    void invalidAdapterJsonIsABadGateway() throws Exception {
        REPLIES.put("/telemetry", new Reply(200, "{not json"));
        mvc.perform(get("/api/trainer/telemetry")).andExpect(status().isBadGateway());
    }

    @Test
    void healthIsLocal() throws Exception {
        mvc.perform(get("/api/trainer/health"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("UP"));
    }
}
