import java.io.IOException;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.TimeUnit;

/** Java CLI/SDK entry point for the foreground Python engine; no shell or server. */
public final class OutlandsAgentClient {
    private OutlandsAgentClient() { }

    private static void stop(Process process) {
        List<ProcessHandle> descendants = process.descendants().toList();
        process.destroy();
        try {
            process.waitFor(3, TimeUnit.SECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        } finally {
            for (ProcessHandle child : descendants) if (child.isAlive()) child.destroyForcibly();
            if (process.isAlive()) process.destroyForcibly();
        }
    }

    /** Inherit the engine's console; engine owns the task and request budgets. */
    public static int run(Path python, Path engine, List<String> arguments)
            throws IOException, InterruptedException {
        if (!python.isAbsolute() || !engine.isAbsolute()) {
            throw new IllegalArgumentException("Absolute interpreter and engine paths required");
        }
        List<String> command = new ArrayList<>(List.of(python.toString(), "-B", engine.toString()));
        command.addAll(arguments);
        ProcessBuilder builder = new ProcessBuilder(command).inheritIO();
        builder.environment().clear();
        builder.environment().put("PATH", "/usr/bin:/bin");
        builder.environment().put("LANG", "C.UTF-8");
        builder.environment().put("PYTHONNOUSERSITE", "1");
        Process process = builder.start();
        Thread shutdown = new Thread(() -> stop(process));
        Runtime.getRuntime().addShutdownHook(shutdown);
        try {
            return process.waitFor();
        } catch (InterruptedException e) {
            stop(process);
            Thread.currentThread().interrupt();
            throw e;
        } finally {
            Runtime.getRuntime().removeShutdownHook(shutdown);
        }
    }

    public static void main(String[] args) {
        if (args.length < 2) {
            System.err.println("Usage: java OutlandsAgentClient.java /absolute/python /absolute/agent.py ENGINE_ARGUMENTS...");
            System.exit(2);
        }
        try {
            int code = run(Path.of(args[0]), Path.of(args[1]), Arrays.asList(args).subList(2, args.length));
            System.exit(code);
        } catch (IOException | IllegalArgumentException e) {
            System.err.println("Client could not launch the engine");
            System.exit(2);
        } catch (InterruptedException e) {
            System.err.println("Client interrupted; inspect private run/state records before another run");
            System.exit(130);
        }
    }
}
