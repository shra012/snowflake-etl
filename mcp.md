# Recreate mcp-java (without `excercise/`)

Step-by-step guide to rebuild this project from scratch on a new machine. This covers everything **except** the `excercise/` folder (course demos and exercise PDFs).

## What you get

A Spring Boot **STDIO MCP server** with:

| Capability | Items |
|------------|-------|
| **Sync tools** (`@Tool`) | `echo`, `add` |
| **Async tools** (`@McpTool`) | `fetch-url` |
| **Resources** (`@McpResource`) | `policy-documents.json`, policy PDFs by ID, `work-calendars.json`, work calendar by location |

Stack: **Java 25**, **Spring Boot 3.5.14**, **Spring AI 1.1.7**, `spring-ai-starter-mcp-server-webflux`.

---

## Prerequisites

```bash
brew install openjdk@25 maven jenv node
```

Optional but recommended for per-project Java version:

```bash
jenv add /opt/homebrew/opt/openjdk@25/libexec/openjdk.jdk/Contents/Home
```

Add to `~/.zshrc`:

```bash
export PATH="$HOME/.jenv/bin:$PATH"
eval "$(jenv init -)"
jenv enable-plugin export 2>/dev/null || true
```

---

## 1. Create project layout

```bash
mkdir -p mcp-java/src/main/java/com/example/mcp/{calendar,documents}
mkdir -p mcp-java/src/main/resources
mkdir -p mcp-java/.cursor
mkdir -p mcp-java/.vscode
mkdir -p mcp-java/data/policy-documents
cd mcp-java
```

### Policy document PDFs

The server reads PDFs from a local directory (configured in `application.yml`). Without `excercise/`, use `data/policy-documents/` instead.

Copy sample PDFs from the [Pluralsight course repo](https://github.com/kamranayub/pluralsight-course-mcp-in-practice/tree/master/m2-token-counting/pdfs) if you want the policy resources to return real files:

```bash
# example — adjust source path to wherever you cloned the course repo
cp /path/to/pluralsight-course-mcp-in-practice/m2-token-counting/pdfs/*.pdf data/policy-documents/
```

---

## 2. Root files

### `pom.xml`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>

    <parent>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-parent</artifactId>
        <version>3.5.14</version>
        <relativePath/>
    </parent>

    <groupId>com.example</groupId>
    <artifactId>mcp-java</artifactId>
    <version>0.0.1-SNAPSHOT</version>
    <name>mcp-java</name>
    <description>Simple STDIO MCP server using Spring AI and mcp-spring-webflux</description>

    <properties>
        <java.version>25</java.version>
        <spring-ai.version>1.1.7</spring-ai.version>
    </properties>

    <dependencyManagement>
        <dependencies>
            <dependency>
                <groupId>org.springframework.ai</groupId>
                <artifactId>spring-ai-bom</artifactId>
                <version>${spring-ai.version}</version>
                <type>pom</type>
                <scope>import</scope>
            </dependency>
        </dependencies>
    </dependencyManagement>

    <dependencies>
        <dependency>
            <groupId>org.springframework.ai</groupId>
            <artifactId>spring-ai-starter-mcp-server-webflux</artifactId>
        </dependency>
    </dependencies>

    <build>
        <plugins>
            <plugin>
                <groupId>org.springframework.boot</groupId>
                <artifactId>spring-boot-maven-plugin</artifactId>
            </plugin>
        </plugins>
    </build>
</project>
```

### `.gitignore`

```
target/
.idea/
*.iml
.classpath
.project
.settings/
.DS_Store
*.log
```

### `.java-version`

```
25
```

Set jenv for this project:

```bash
jenv local 25
```

### `README.md`

Copy or adapt from the project `README.md` — it documents build, Cursor wiring, and configuration.

### `inspector.config.json`

Replace the JAR path with your absolute project path:

```json
{
  "mcpServers": {
    "default-server": {
      "type": "stdio",
      "command": "/opt/homebrew/opt/openjdk@25/bin/java",
      "args": [
        "-jar",
        "/ABSOLUTE/PATH/TO/mcp-java/target/mcp-java-0.0.1-SNAPSHOT.jar"
      ]
    }
  }
}
```

Run Inspector:

```bash
mvn package -DskipTests
npx @modelcontextprotocol/inspector --config inspector.config.json
```

---

## 3. IDE / MCP client config

### `.cursor/mcp.json` (Cursor — project-scoped)

Cursor does **not** read `.vscode/mcp.json`. Use `.cursor/mcp.json`:

```json
{
    "mcpServers": {
        "mcp-java": {
            "command": "/Users/YOU/.jenv/shims/java",
            "cwd": "/ABSOLUTE/PATH/TO/mcp-java",
            "args": [
                "-jar",
                "target/mcp-java-0.0.1-SNAPSHOT.jar"
            ]
        }
    }
}
```

Notes:

- Use an **absolute path** to `java` (jenv shim or Homebrew OpenJDK). Cursor does not inherit your shell `PATH`.
- `cwd` lets jenv read `.java-version`.
- Reload MCP in **Cursor Settings → MCP** after changes.

Alternative without jenv:

```json
"command": "/opt/homebrew/opt/openjdk@25/bin/java"
```

### `.vscode/settings.json`

```json
{
    "java.compile.nullAnalysis.mode": "automatic"
}
```

---

## 4. Application config

### `src/main/resources/application.yml`

```yaml
spring:
  main:
    # STDIO transport uses stdin/stdout — no embedded web server
    web-application-type: none
    banner-mode: off

logging:
  # Console output corrupts STDIO JSON-RPC messages
  pattern:
    console:

spring.ai.mcp.server:
  stdio: true
  name: mcp-java-server
  version: 0.0.1
  # ASYNC server: @McpTool/@McpResource I/O methods return Mono/Flux; @Tool sync methods are auto-wrapped
  type: ASYNC
  instructions: "A simple MCP server with echo, calculator, fetch-url tools, and HRM policy/calendar resources."

app:
  policy-documents-dir: /ABSOLUTE/PATH/TO/mcp-java/data/policy-documents
```

Replace `policy-documents-dir` with your real absolute path.

---

## 5. Java source files

### `src/main/java/com/example/mcp/McpServerApplication.java`

```java
package com.example.mcp;

import org.springframework.ai.tool.ToolCallbackProvider;
import org.springframework.ai.tool.method.MethodToolCallbackProvider;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;
import org.springframework.web.reactive.function.client.WebClient;

@SpringBootApplication
public class McpServerApplication {

	public static void main(String[] args) {
		SpringApplication.run(McpServerApplication.class, args);
	}

	@Bean
	ToolCallbackProvider toolCallbacks(EchoTools echoTools) {
		return MethodToolCallbackProvider.builder().toolObjects(echoTools).build();
	}

	@Bean
	WebClient webClient() {
		return WebClient.builder().build();
	}

}
```

### `src/main/java/com/example/mcp/EchoTools.java`

Sync tools registered via `MethodToolCallbackProvider`:

```java
package com.example.mcp;

import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Service;

@Service
public class EchoTools {

	@Tool(description = "Echoes the input text back to the caller")
	public String echo(@ToolParam(description = "Text to echo") String text) {
		return "Echo: " + text;
	}

	@Tool(description = "Adds two integers and returns the sum")
	public int add(
			@ToolParam(description = "First number") int a,
			@ToolParam(description = "Second number") int b) {
		return a + b;
	}

}
```

### `src/main/java/com/example/mcp/IoTools.java`

Async I/O tool — auto-discovered by the `@McpTool` annotation scanner:

```java
package com.example.mcp;

import org.springaicommunity.mcp.annotation.McpTool;
import org.springaicommunity.mcp.annotation.McpToolParam;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

@Service
public class IoTools {

	private final WebClient webClient;

	public IoTools(WebClient webClient) {
		this.webClient = webClient;
	}

	@McpTool(name = "fetch-url", description = "Fetches text content from a URL over HTTP")
	public Mono<String> fetchUrl(@McpToolParam(description = "URL to fetch", required = true) String url) {
		return webClient.get()
				.uri(url)
				.retrieve()
				.bodyToMono(String.class)
				.map(body -> body.length() > 2000 ? body.substring(0, 2000) + "..." : body);
	}

}
```

---

## 6. Policy document resources

### `src/main/java/com/example/mcp/documents/PlanDocumentCategory.java`

```java
package com.example.mcp.documents;

public enum PlanDocumentCategory {
	Absence,
	Medical,
	Dental,
	Vision,
	Retirement
}
```

### `src/main/java/com/example/mcp/documents/DocumentInfo.java`

```java
package com.example.mcp.documents;

public record DocumentInfo(
		String documentId,
		String title,
		String description,
		PlanDocumentCategory category) {
}
```

### `src/main/java/com/example/mcp/documents/PolicyDocumentService.java`

```java
package com.example.mcp.documents;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Base64;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.stream.Stream;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

@Service
public class PolicyDocumentService {

	private static final Map<String, DocumentInfo> KNOWN_DOCUMENTS = Map.of(
			"Globomantics_GloboDental_Plan_SPD.pdf",
			new DocumentInfo(
					"Globomantics_GloboDental_Plan_SPD.pdf",
					"GloboDental Plan SPD",
					"Globomantics dental benefit plan summary plan description",
					PlanDocumentCategory.Dental),
			"Globomantics_GloboVision_Plan_SPD.pdf",
			new DocumentInfo(
					"Globomantics_GloboVision_Plan_SPD.pdf",
					"GloboVision Plan SPD",
					"Globomantics vision benefit plan summary plan description",
					PlanDocumentCategory.Vision),
			"Globomantics_GloboRetirement_401k_SPD.pdf",
			new DocumentInfo(
					"Globomantics_GloboRetirement_401k_SPD.pdf",
					"GloboRetirement 401k SPD",
					"Globomantics retirement benefit plan summary plan description",
					PlanDocumentCategory.Retirement),
			"Globomantics_MedGlobo_SPD.pdf",
			new DocumentInfo(
					"Globomantics_MedGlobo_SPD.pdf",
					"MedGlobo SPD",
					"Globomantics medical benefit plan summary plan description",
					PlanDocumentCategory.Medical));

	private final Path documentsDir;

	public PolicyDocumentService(@Value("${app.policy-documents-dir}") String documentsDir) {
		this.documentsDir = Path.of(documentsDir).toAbsolutePath().normalize();
	}

	public List<DocumentInfo> listDocuments() throws IOException {
		if (!Files.isDirectory(documentsDir)) {
			throw new IllegalStateException("Policy documents directory not found: " + documentsDir);
		}

		try (Stream<Path> files = Files.list(documentsDir)) {
			return files.filter(Files::isRegularFile)
					.filter(path -> path.getFileName().toString().endsWith(".pdf"))
					.sorted(Comparator.comparing(path -> path.getFileName().toString()))
					.map(path -> toDocumentInfo(path.getFileName().toString()))
					.toList();
		}
	}

	public String readDocumentBase64(String documentId) throws IOException {
		Path documentPath = resolveDocumentPath(documentId);
		if (!Files.exists(documentPath)) {
			return null;
		}
		return Base64.getEncoder().encodeToString(Files.readAllBytes(documentPath));
	}

	private Path resolveDocumentPath(String documentId) {
		Path resolved = documentsDir.resolve(documentId).normalize();
		if (!resolved.startsWith(documentsDir)) {
			throw new IllegalArgumentException("Document path must stay under policy documents directory");
		}
		return resolved;
	}

	private DocumentInfo toDocumentInfo(String documentId) {
		DocumentInfo known = KNOWN_DOCUMENTS.get(documentId);
		if (known != null) {
			return known;
		}

		String title = documentId.endsWith(".pdf")
				? documentId.substring(0, documentId.length() - 4)
				: documentId;
		return new DocumentInfo(documentId, title, null, null);
	}

}
```

### `src/main/java/com/example/mcp/documents/PolicyDocumentResources.java`

```java
package com.example.mcp.documents;

import java.util.List;

import org.springaicommunity.mcp.annotation.McpResource;
import org.springframework.stereotype.Service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;

import io.modelcontextprotocol.spec.McpSchema.BlobResourceContents;
import io.modelcontextprotocol.spec.McpSchema.ReadResourceResult;
import io.modelcontextprotocol.spec.McpSchema.ResourceContents;
import io.modelcontextprotocol.spec.McpSchema.TextResourceContents;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

@Service
public class PolicyDocumentResources {

	public static final String RESOURCE_BENEFIT_PLAN_DOCUMENTS_URI = "globomantics://hrm/documents";

	public static final String RESOURCE_BENEFIT_PLAN_DOCUMENT_URI = "globomantics://hrm/documents/{documentId}";

	private final PolicyDocumentService documentService;

	private final ObjectMapper objectMapper;

	public PolicyDocumentResources(PolicyDocumentService documentService, ObjectMapper objectMapper) {
		this.documentService = documentService;
		this.objectMapper = objectMapper;
	}

	@McpResource(
			uri = RESOURCE_BENEFIT_PLAN_DOCUMENTS_URI,
			name = "policy-documents.json",
			title = "HR Benefit Plan and Policy Documents",
			mimeType = "application/json",
			description = "Provides a list of policy documents available to employees. Each policy document is a PDF file and may relate to a specific benefit plan that is available to the employee.")
	public Mono<ReadResourceResult> policyDocuments() {
		return Mono.fromCallable(this::buildPolicyDocumentList)
				.subscribeOn(Schedulers.boundedElastic());
	}

	@McpResource(
			uri = RESOURCE_BENEFIT_PLAN_DOCUMENT_URI,
			name = "HR Benefit Plan and Policy Document by ID",
			mimeType = "application/pdf",
			description = "Retrieves a specific HRM benefit plan document by its document ID (e.g. Globomantics_GloboDental_Plan_SPD.pdf)")
	public Mono<ReadResourceResult> policyDocumentById(String documentId) {
		return Mono.fromCallable(() -> buildPolicyDocument(documentId))
				.subscribeOn(Schedulers.boundedElastic());
	}

	private ReadResourceResult buildPolicyDocumentList() throws Exception {
		List<ResourceContents> contents = documentService.listDocuments().stream()
				.<ResourceContents>map(this::toDocumentListEntry)
				.toList();
		return new ReadResourceResult(contents);
	}

	private ReadResourceResult buildPolicyDocument(String documentId) throws Exception {
		String base64Content = documentService.readDocumentBase64(documentId);
		if (base64Content == null || base64Content.isBlank()) {
			throw new IllegalStateException("Benefit plan document content is empty");
		}

		String uri = RESOURCE_BENEFIT_PLAN_DOCUMENT_URI.replace("{documentId}", documentId);
		ResourceContents content = new BlobResourceContents(uri, "application/pdf", base64Content);
		return new ReadResourceResult(List.of(content));
	}

	private TextResourceContents toDocumentListEntry(DocumentInfo info) {
		try {
			String text = objectMapper.writeValueAsString(info);
			String uri = RESOURCE_BENEFIT_PLAN_DOCUMENT_URI.replace("{documentId}", info.documentId());
			return new TextResourceContents(uri, "application/json", text);
		}
		catch (JsonProcessingException ex) {
			throw new IllegalStateException("Failed to serialize document info", ex);
		}
	}

}
```

---

## 7. Work calendar resources

### `src/main/java/com/example/mcp/calendar/WorkLocation.java`

```java
package com.example.mcp.calendar;

public enum WorkLocation {
	UnitedStates,
	India
}
```

### `src/main/java/com/example/mcp/calendar/WorkHoliday.java`

```java
package com.example.mcp.calendar;

public record WorkHoliday(String day, String holiday) {
}
```

### `src/main/java/com/example/mcp/calendar/AnnualHolidayCalendar.java`

```java
package com.example.mcp.calendar;

import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.List;

public record AnnualHolidayCalendar(int year, List<WorkHoliday> holidays) {

	private static final DateTimeFormatter ISO_DATE = DateTimeFormatter.ISO_LOCAL_DATE;

	public static AnnualHolidayCalendar createForYear(int year, WorkLocation location) {
		List<WorkHoliday> holidays = location == WorkLocation.UnitedStates
				? createUsFederalHolidays(year)
				: createIndiaHolidays(year);
		return new AnnualHolidayCalendar(year, holidays);
	}

	private static List<WorkHoliday> createUsFederalHolidays(int year) {
		return List.of(
				holiday(year, 1, 1, "New Year's Day"),
				holiday(year, 1, 15, "Martin Luther King Jr. Day"),
				holiday(year, 2, 19, "Presidents' Day"),
				holiday(year, 5, 28, "Memorial Day"),
				holiday(year, 6, 19, "Juneteenth National Independence Day"),
				holiday(year, 7, 4, "Independence Day"),
				holiday(year, 9, 3, "Labor Day"),
				holiday(year, 10, 8, "Indigenous Peoples' Day"),
				holiday(year, 11, 11, "Veterans Day"),
				holiday(year, 11, 22, "Thanksgiving Day"),
				holiday(year, 12, 25, "Christmas Day"));
	}

	private static List<WorkHoliday> createIndiaHolidays(int year) {
		return List.of(
				holiday(year, 1, 26, "Republic Day"),
				holiday(year, 8, 15, "Independence Day"),
				holiday(year, 4, 18, "Good Friday"),
				holiday(year, 10, 2, "Gandhi Jayanti"),
				holiday(year, 10, 2, "Dussehra"),
				holiday(year, 12, 25, "Christmas Day"),
				holiday(year, 3, 14, "Holi"),
				holiday(year, 8, 9, "Raksha Bandhan"),
				holiday(year, 10, 20, "Diwali"));
	}

	private static WorkHoliday holiday(int year, int month, int day, String name) {
		return new WorkHoliday(LocalDate.of(year, month, day).format(ISO_DATE), name);
	}

}
```

### `src/main/java/com/example/mcp/calendar/WorkCalendarResources.java`

```java
package com.example.mcp.calendar;

import java.time.Year;
import java.util.Map;

import org.springaicommunity.mcp.annotation.McpResource;
import org.springframework.stereotype.Service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;

import reactor.core.publisher.Mono;

@Service
public class WorkCalendarResources {

	public static final String RESOURCE_WORK_CALENDAR_URI = "globomantics://hrm/calendars/work";

	public static final String RESOURCE_WORK_BY_LOCATION_CALENDAR_URI = "globomantics://hrm/calendars/work/{year}/{location}";

	private final ObjectMapper objectMapper;

	public WorkCalendarResources(ObjectMapper objectMapper) {
		this.objectMapper = objectMapper;
	}

	@McpResource(
			uri = RESOURCE_WORK_CALENDAR_URI,
			name = "work-calendars.json",
			title = "Work Holiday Calendars",
			mimeType = "application/json",
			description = "Returns the holiday calendars for different work locations (United States and India).")
	public Mono<String> workCalendars() {
		int year = Year.now().getValue();
		Map<String, AnnualHolidayCalendar> workCalendarResource = Map.of(
				"US", AnnualHolidayCalendar.createForYear(year, WorkLocation.UnitedStates),
				"IN", AnnualHolidayCalendar.createForYear(year, WorkLocation.India));
		return Mono.just(toJson(workCalendarResource));
	}

	@McpResource(
			uri = RESOURCE_WORK_BY_LOCATION_CALENDAR_URI,
			name = "Work Calendar by Location",
			mimeType = "application/json",
			description = "The work calendar for a specific year and location")
	public Mono<String> workCalendarByLocation(String year, String location) {
		WorkLocation workLocation = WorkLocation.valueOf(location);
		return Mono.just(toJson(AnnualHolidayCalendar.createForYear(Integer.parseInt(year), workLocation)));
	}

	private String toJson(Object value) {
		try {
			return objectMapper.writeValueAsString(value);
		}
		catch (JsonProcessingException ex) {
			throw new IllegalStateException("Failed to serialize calendar resource", ex);
		}
	}

}
```

---

## 8. Build and verify

Always do a **clean** Maven build (avoids stale IDE-compiled classes):

```bash
mvn clean package -DskipTests
```

### Expected MCP surface

**Tools**

| Name | Type | Registration |
|------|------|--------------|
| `echo` | sync `@Tool` | `ToolCallbackProvider` bean |
| `add` | sync `@Tool` | `ToolCallbackProvider` bean |
| `fetch-url` | async `@McpTool` | annotation scanner |

**Resources**

| Name | URI |
|------|-----|
| `policy-documents.json` | `globomantics://hrm/documents` |
| Policy PDF by ID | `globomantics://hrm/documents/{documentId}` |
| `work-calendars.json` | `globomantics://hrm/calendars/work` |
| Work calendar by location | `globomantics://hrm/calendars/work/{year}/{location}` |

Example reads:

- `globomantics://hrm/documents`
- `globomantics://hrm/documents/Globomantics_GloboDental_Plan_SPD.pdf`
- `globomantics://hrm/calendars/work`
- `globomantics://hrm/calendars/work/2026/UnitedStates`

---

## 9. Architecture notes

### ASYNC server rules

With `spring.ai.mcp.server.type: ASYNC`:

| Annotation | Sync return | Async return |
|------------|-------------|--------------|
| `@Tool` | `String`, `int`, etc. | Do **not** return `Mono` — gets serialized as an object |
| `@McpTool` | Plain types are **skipped** | Return `Mono<T>` or `Flux<T>` |
| `@McpResource` | Plain `String` is **skipped** | Return `Mono<String>` or `Mono<ReadResourceResult>` |

URI template variables must be **`String`** parameters (e.g. `{year}` → `String year`, not `int`).

Blocking I/O on an async server: wrap with `Mono.fromCallable(...).subscribeOn(Schedulers.boundedElastic())`.

### STDIO gotchas

- `spring.main.web-application-type: none` — no HTTP server
- `logging.pattern.console:` (empty) — keeps stdout clean for JSON-RPC
- Logback may log `Empty or null pattern` once at startup — harmless
- View MCP logs in Cursor: **View → Output** → channel `MCP project-0-...`

### Cursor vs VS Code MCP config

| IDE | Project config path | Root key |
|-----|---------------------|----------|
| Cursor | `.cursor/mcp.json` | `mcpServers` |
| VS Code | `.vscode/mcp.json` | `servers` |

---

## 10. Final directory tree (no `excercise/`)

```
mcp-java/
├── .cursor/
│   └── mcp.json
├── .java-version
├── .vscode/
│   └── settings.json
├── .gitignore
├── README.md
├── RECREATE.md
├── inspector.config.json
├── pom.xml
├── data/
│   └── policy-documents/          # PDFs go here
│       └── *.pdf
└── src/main/
    ├── java/com/example/mcp/
    │   ├── McpServerApplication.java
    │   ├── EchoTools.java
    │   ├── IoTools.java
    │   ├── calendar/
    │   │   ├── AnnualHolidayCalendar.java
    │   │   ├── WorkCalendarResources.java
    │   │   ├── WorkHoliday.java
    │   │   └── WorkLocation.java
    │   └── documents/
    │       ├── DocumentInfo.java
    │       ├── PlanDocumentCategory.java
    │       ├── PolicyDocumentResources.java
    │       └── PolicyDocumentService.java
    └── resources/
        └── application.yml
```

---

## References

- [Spring AI MCP Server Boot Starter](https://docs.spring.io/spring-ai/reference/api/mcp/mcp-server-boot-starter-docs.html)
- [MCP Java SDK Server docs](https://java.sdk.modelcontextprotocol.io/latest/server/)
- [Pluralsight course repo](https://github.com/kamranayub/pluralsight-course-mcp-in-practice) (C# reference — not required to run this Java server)
