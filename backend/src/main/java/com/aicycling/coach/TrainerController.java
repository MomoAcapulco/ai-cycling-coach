package com.aicycling.coach;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.springframework.beans.factory.annotation.Value;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
import org.springframework.web.bind.annotation.RestController;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Map;

/**
 * Forwards the web client's calls to the local Python trainer adapter.
 *
 * <p>The adapter's JSON is passed through untouched, so a field added in Python reaches React without a
 * Java change (until v4.2.2 a typed record dropped every field it did not declare). The adapter's own
 * HTTP status is preserved: a 409 or 400 from Python stays a 409 or 400, and only a connection failure
 * is reported as "adapter offline".
 *
 * <p>One {@link HttpClient} is used for every call. POST bodies are sent from a byte array, so they carry
 * a Content-Length: the Python {@code BaseHTTPRequestHandler} does not parse chunked request bodies.
 */
@RestController
@RequestMapping("/api/trainer")
public class TrainerController {
    static final Duration CONNECT_TIMEOUT = Duration.ofSeconds(3);
    static final Duration REQUEST_TIMEOUT = Duration.ofSeconds(8);
    /** Applying settings stops the Bluetooth workers (up to 8 s) before starting the new ones. */
    static final Duration ADMIN_TIMEOUT = Duration.ofSeconds(30);
    static final String PREFIX = "/api/trainer";

    private final HttpClient http = HttpClient.newBuilder().connectTimeout(CONNECT_TIMEOUT).build();
    private final ObjectMapper json;
    private final String adapterUrl;

    public TrainerController(@Value("${trainer.adapter.url:http://127.0.0.1:8766}") String adapterUrl,
                             ObjectMapper json) {
        this.adapterUrl = adapterUrl.replaceAll("/+$", "");
        this.json = json;
    }

    @GetMapping("/telemetry")
    public ResponseEntity<JsonNode> telemetry() {
        return forward(get("/telemetry"));
    }

    @GetMapping("/replay/session")
    public ResponseEntity<JsonNode> replaySession() {
        return forward(get("/replay/session"));
    }

    @GetMapping("/replay/state")
    public ResponseEntity<JsonNode> replayState() {
        return forward(get("/replay/state"));
    }

    /**
     * Admin page and device registry, passed through as they are: GET/POST/DELETE on /admin/** and
     * /devices/**, query string included (recording upload uses ?name=), body and Content-Type kept.
     */
    @RequestMapping(value = {"/admin/**", "/devices", "/devices/**", "/session", "/session/**", "/sessions"},
            method = {RequestMethod.GET, RequestMethod.POST, RequestMethod.DELETE})
    public ResponseEntity<JsonNode> admin(HttpServletRequest servletRequest,
                                          @RequestBody(required = false) byte[] body) {
        String path = servletRequest.getRequestURI().substring(servletRequest.getContextPath().length());
        if (!path.startsWith(PREFIX)) {
            return error(HttpStatus.NOT_FOUND, "Unknown path");
        }
        String query = servletRequest.getQueryString();
        HttpRequest.Builder request = HttpRequest.newBuilder(
                        URI.create(adapterUrl + path.substring(PREFIX.length()) + (query == null ? "" : "?" + query)))
                .timeout(ADMIN_TIMEOUT)
                .header("Accept", "application/json");
        byte[] payload = body == null ? new byte[0] : body;
        switch (servletRequest.getMethod()) {
            case "POST" -> {
                String type = servletRequest.getContentType();
                request.header("Content-Type", type == null ? "application/octet-stream" : type)
                        .POST(HttpRequest.BodyPublishers.ofByteArray(payload));
            }
            case "DELETE" -> request.DELETE();
            default -> request.GET();
        }
        return forward(request.build());
    }

    @PostMapping("/replay/control")
    public ResponseEntity<JsonNode> replayControl(@RequestBody Map<String, Object> command) {
        return post("/replay/control", command);
    }

    /** Shift: display only in REPLAY, a real request when the trainer shifts natively (409 otherwise). */
    @PostMapping("/gear")
    public ResponseEntity<JsonNode> gear(@RequestBody Map<String, Object> command) {
        return post("/gear", command);
    }

    /** Grade chosen by the rider: {"gradePercent": n}. 409 without native control on the trainer, 400 if invalid. */
    @PostMapping("/grade")
    public ResponseEntity<JsonNode> grade(@RequestBody Map<String, Object> command) {
        return post("/grade", command);
    }

    @PostMapping("/replay/gear")
    public ResponseEntity<JsonNode> replayGear(@RequestBody Map<String, Object> command) {
        return post("/replay/gear", command);
    }

    /**
     * Download of a finished session's file (CSV, summary JSON or raw capture), passed through byte for byte
     * with the adapter's Content-Type and Content-Disposition. The adapter only serves session_* names.
     */
    @GetMapping("/sessions/{file:.+}")
    public ResponseEntity<byte[]> sessionFile(@PathVariable("file") String file) {
        HttpRequest request = HttpRequest.newBuilder(URI.create(adapterUrl + "/sessions/"
                        + java.net.URLEncoder.encode(file, java.nio.charset.StandardCharsets.UTF_8).replace("+", "%20")))
                .timeout(ADMIN_TIMEOUT)
                .GET()
                .build();
        try {
            HttpResponse<byte[]> response = http.send(request, HttpResponse.BodyHandlers.ofByteArray());
            ResponseEntity.BodyBuilder out = ResponseEntity.status(response.statusCode());
            response.headers().firstValue("Content-Type").ifPresent(v -> out.header("Content-Type", v));
            response.headers().firstValue("Content-Disposition").ifPresent(v -> out.header("Content-Disposition", v));
            return out.body(response.body());
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
            return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE).build();
        } catch (IOException ex) {
            return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE).build();
        }
    }

    /** Health of the Java API itself; the adapter's health is part of /telemetry. */
    @GetMapping("/health")
    public Map<String, String> health() {
        return Map.of("status", "UP");
    }

    private HttpRequest.Builder request(String path) {
        return HttpRequest.newBuilder(URI.create(adapterUrl + path))
                .timeout(REQUEST_TIMEOUT)
                .header("Accept", "application/json");
    }

    private HttpRequest get(String path) {
        return request(path).GET().build();
    }

    private ResponseEntity<JsonNode> post(String path, Map<String, Object> command) {
        byte[] payload;
        try {
            payload = json.writeValueAsBytes(command);
        } catch (JsonProcessingException ex) {
            return error(HttpStatus.BAD_REQUEST, "Invalid JSON: " + ex.getOriginalMessage());
        }
        return forward(request(path)
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofByteArray(payload))
                .build());
    }

    private ResponseEntity<JsonNode> forward(HttpRequest request) {
        HttpResponse<String> response;
        try {
            response = http.send(request, HttpResponse.BodyHandlers.ofString());
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
            return error(HttpStatus.SERVICE_UNAVAILABLE, "Interrupted while calling the trainer adapter");
        } catch (IOException ex) {
            // Connection refused, connect timeout or request timeout: the adapter is not answering.
            return error(HttpStatus.SERVICE_UNAVAILABLE,
                    "Trainer adapter is offline. Check Python adapter logs. (" + ex.getClass().getSimpleName() + ")");
        }
        int code = response.statusCode();
        String body = response.body();
        if (code < 200 || code >= 300) {
            ObjectNode node = errorNode("Trainer adapter rejected request");
            node.put("adapterStatus", code);
            node.put("adapterResponse", body);
            return ResponseEntity.status(code).body(node);
        }
        if (body == null || body.isBlank()) {
            return error(HttpStatus.BAD_GATEWAY, "Empty adapter response");
        }
        try {
            // Keep the adapter's exact success code too (e.g. 201 Created for an uploaded recording).
            return ResponseEntity.status(code).body(json.readTree(body));
        } catch (JsonProcessingException ex) {
            return error(HttpStatus.BAD_GATEWAY, "Adapter returned invalid JSON: " + ex.getOriginalMessage());
        }
    }

    private ObjectNode errorNode(String message) {
        ObjectNode node = json.createObjectNode();
        node.put("error", message);
        return node;
    }

    private ResponseEntity<JsonNode> error(HttpStatus status, String message) {
        return ResponseEntity.status(status).body(errorNode(message));
    }
}
