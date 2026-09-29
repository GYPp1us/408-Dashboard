import android.app.UiAutomation;
import android.accessibilityservice.AccessibilityServiceInfo;
import android.graphics.Rect;
import android.os.HandlerThread;
import android.os.Looper;
import android.os.SystemClock;
import android.view.InputDevice;
import android.view.MotionEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import android.view.accessibility.AccessibilityWindowInfo;
import java.lang.reflect.Constructor;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.List;
import org.json.JSONArray;
import org.json.JSONObject;

/** Shell app_process helper. Snapshot never waits for idle or reads an old dump. */
public final class LiveUiSnapshot {
    private static final int MAX_NODES = 10000;
    private static int visited;
    private static String action;
    private static String target;
    private static String packageFilter;
    private static final List<AccessibilityNodeInfo> matches = new ArrayList<>();
    private static final JSONArray matchPayloads = new JSONArray();

    private static String string(CharSequence value) { return value == null ? "" : value.toString(); }

    private static boolean hasWindowRoot(List<AccessibilityWindowInfo> windows) {
        for (AccessibilityWindowInfo window : windows) {
            AccessibilityNodeInfo root = window.getRoot();
            if (root != null) {
                root.recycle();
                return true;
            }
        }
        return false;
    }

    private static JSONObject walk(AccessibilityNodeInfo node, String path, int depth) throws Exception {
        if (node == null || depth > 80 || ++visited > MAX_NODES) return null;
        Rect bounds = new Rect();
        node.getBoundsInScreen(bounds);
        JSONObject item = new JSONObject();
        item.put("path", path);
        item.put("text", string(node.getText()));
        item.put("description", string(node.getContentDescription()));
        item.put("resourceId", string(node.getViewIdResourceName()));
        item.put("package", string(node.getPackageName()));
        item.put("class", string(node.getClassName()));
        item.put("bounds", new JSONArray(new int[]{bounds.left, bounds.top, bounds.right, bounds.bottom}));
        item.put("clickable", node.isClickable());
        item.put("enabled", node.isEnabled());
        item.put("visible", node.isVisibleToUser());
        item.put("checked", node.isChecked());
        item.put("selected", node.isSelected());
        boolean selected = target != null && (action.endsWith("-id")
            ? target.equals(string(node.getViewIdResourceName()))
            : target.equals(string(node.getText())) || target.equals(string(node.getContentDescription())));
        if (selected && (packageFilter == null || packageFilter.equals(string(node.getPackageName()))) && node.isVisibleToUser()) {
            matches.add(AccessibilityNodeInfo.obtain(node));
            matchPayloads.put(new JSONObject(item.toString()));
        }
        JSONArray children = new JSONArray();
        for (int index = 0; index < node.getChildCount(); index++) {
            AccessibilityNodeInfo child = node.getChild(index);
            if (child == null) continue;
            try {
                JSONObject result = walk(child, path + "/" + index, depth + 1);
                if (result != null) children.put(result);
            } finally { child.recycle(); }
        }
        item.put("children", children);
        return item;
    }

    private static JSONObject tap(UiAutomation automation) throws Exception {
        if (matches.size() != 1) throw new IllegalStateException("Expected one visible exact match; found " + matches.size() + ". Use find-text/find-id and --package first.");
        AccessibilityNodeInfo node = matches.get(0);
        JSONObject result = new JSONObject();
        result.put("target", target);
        result.put("node", matchPayloads.getJSONObject(0));
        if (!node.isEnabled()) throw new IllegalStateException("Matched node is disabled");
        // Use accessibility click on the nearest enabled clickable ancestor first.
        AccessibilityNodeInfo current = AccessibilityNodeInfo.obtain(node);
        try {
            for (int depth = 0; current != null && depth < 8; depth++) {
                if (current.isClickable() && current.isEnabled() && current.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
                    result.put("clicked", true);
                    result.put("method", "accessibility_action");
                    return result;
                }
                AccessibilityNodeInfo parent = current.getParent();
                current.recycle();
                current = parent;
            }
        } finally { if (current != null) current.recycle(); }
        Rect bounds = new Rect();
        node.getBoundsInScreen(bounds);
        if (bounds.isEmpty()) throw new IllegalStateException("Matched node has empty bounds");
        long downTime = SystemClock.uptimeMillis();
        MotionEvent down = MotionEvent.obtain(downTime, downTime, MotionEvent.ACTION_DOWN, bounds.exactCenterX(), bounds.exactCenterY(), 0);
        MotionEvent up = MotionEvent.obtain(downTime, downTime + 80, MotionEvent.ACTION_UP, bounds.exactCenterX(), bounds.exactCenterY(), 0);
        down.setSource(InputDevice.SOURCE_TOUCHSCREEN);
        up.setSource(InputDevice.SOURCE_TOUCHSCREEN);
        try {
            boolean pressed = automation.injectInputEvent(down, true);
            boolean released = automation.injectInputEvent(up, true);
            result.put("clicked", pressed && released);
            result.put("method", "bounds_touch");
        } finally { down.recycle(); up.recycle(); }
        return result;
    }

    private static float boundedFloat(String raw, float minimum, float maximum, String name) {
        float value = Float.parseFloat(raw);
        if (Float.isNaN(value) || Float.isInfinite(value) || value < minimum || value > maximum)
            throw new IllegalArgumentException(name + " must be " + minimum + ".." + maximum);
        return value;
    }

    private static JSONObject pinchParameters(String[] args) throws Exception {
        if (args.length != 6) throw new IllegalArgumentException("pinch centerX centerY startSpan endSpan durationMs (physical screen pixels)");
        float x = boundedFloat(args[1], 0, 8192, "centerX");
        float y = boundedFloat(args[2], 0, 8192, "centerY");
        float start = boundedFloat(args[3], 16, 4096, "startSpan");
        float end = boundedFloat(args[4], 16, 4096, "endSpan");
        int duration = Integer.parseInt(args[5]);
        if (duration < 100 || duration > 3000) throw new IllegalArgumentException("durationMs must be 100..3000");
        float half = Math.max(start, end) / 2;
        if (x - half < 0 || x + half > 8192) throw new IllegalArgumentException("Horizontal finger positions must remain within 0..8192");
        return new JSONObject().put("centerX", x).put("centerY", y).put("startSpan", start)
            .put("endSpan", end).put("durationMs", duration).put("coordinates", "physical_screen_pixels");
    }

    private static boolean injectPointers(UiAutomation automation, long downTime, int eventAction,
            int count, float x, float y, float span, JSONArray failures) {
        MotionEvent.PointerProperties[] properties = new MotionEvent.PointerProperties[count];
        MotionEvent.PointerCoords[] coords = new MotionEvent.PointerCoords[count];
        for (int index = 0; index < count; index++) {
            properties[index] = new MotionEvent.PointerProperties();
            properties[index].id = index;
            properties[index].toolType = MotionEvent.TOOL_TYPE_FINGER;
            coords[index] = new MotionEvent.PointerCoords();
            coords[index].x = x + (index == 0 ? -span / 2 : span / 2);
            coords[index].y = y;
            coords[index].pressure = 1;
            coords[index].size = 1;
        }
        MotionEvent event = MotionEvent.obtain(downTime, SystemClock.uptimeMillis(), eventAction,
            count, properties, coords, 0, 0, 1, 1, 0, 0, InputDevice.SOURCE_TOUCHSCREEN, 0);
        try {
            boolean injected = automation.injectInputEvent(event, true);
            if (!injected) failures.put("action=" + eventAction + " injection returned false");
            return injected;
        } catch (RuntimeException error) {
            failures.put("action=" + eventAction + " " + error.toString());
            return false;
        } finally { event.recycle(); }
    }

    private static JSONObject pinch(UiAutomation automation, JSONObject parameters) throws Exception {
        float x = (float)parameters.getDouble("centerX"), y = (float)parameters.getDouble("centerY");
        float start = (float)parameters.getDouble("startSpan"), end = (float)parameters.getDouble("endSpan");
        int duration = parameters.getInt("durationMs"), steps = Math.max(2, duration / 16);
        float currentSpan = start;
        long downTime = SystemClock.uptimeMillis();
        JSONArray failures = new JSONArray();
        int count = 0;
        try {
            count++;
            if (injectPointers(automation, downTime, MotionEvent.ACTION_DOWN, 1, x, y, currentSpan, failures)) {
                count++;
                if (injectPointers(automation, downTime, MotionEvent.ACTION_POINTER_DOWN | (1 << MotionEvent.ACTION_POINTER_INDEX_SHIFT), 2, x, y, currentSpan, failures)) {
                    for (int step = 1; step <= steps; step++) {
                        long wait = downTime + (long)duration * step / steps - SystemClock.uptimeMillis();
                        if (wait > 0) SystemClock.sleep(wait);
                        currentSpan = start + (end - start) * step / steps;
                        count++;
                        if (!injectPointers(automation, downTime, MotionEvent.ACTION_MOVE, 2, x, y, currentSpan, failures)) break;
                    }
                }
            }
        } finally {
            // Always release both pointers, including after failed DOWN/MOVE.
            count += 2;
            injectPointers(automation, downTime, MotionEvent.ACTION_POINTER_UP | (1 << MotionEvent.ACTION_POINTER_INDEX_SHIFT), 2, x, y, currentSpan, failures);
            injectPointers(automation, downTime, MotionEvent.ACTION_UP, 1, x, y, currentSpan, failures);
        }
        return new JSONObject().put("parameters", parameters).put("injected", failures.length() == 0)
            .put("eventCount", count).put("moveStepsRequested", steps).put("failedEvents", failures)
            .put("actualDurationMs", SystemClock.uptimeMillis() - downTime);
    }

    private static String asciiJson(String raw) {
        StringBuilder result = new StringBuilder();
        for (int index = 0; index < raw.length(); index++) {
            char value = raw.charAt(index);
            if (value > 127) result.append(String.format("\\u%04x", (int)value));
            else result.append(value);
        }
        return result.toString();
    }

    public static void main(String[] args) {
        // AccessibilityInteractionClient on Android 15 requires a main Looper
        // even though app_process is not an Activity/application process.
        if (Looper.getMainLooper() == null) Looper.prepareMainLooper();
        HandlerThread handler = new HandlerThread("LiveUiSnapshot");
        UiAutomation automation = null;
        try {
            action = args.length > 0 ? args[0] : "dump";
            JSONObject gesture = action.equals("pinch") ? pinchParameters(args) : null;
            if (!(action.equals("dump") || action.equals("dump-windows") || action.equals("pinch") || action.equals("find-text") || action.equals("tap-text") || action.equals("find-id") || action.equals("tap-id")))
                throw new IllegalArgumentException("dump | dump-windows | pinch centerX centerY startSpan endSpan durationMs | find-text EXACT | tap-text EXACT | find-id ID | tap-id ID [--package PACKAGE]");
            if (!action.equals("dump") && !action.equals("dump-windows") && gesture == null) {
                if (args.length < 2) throw new IllegalArgumentException("An exact target is required");
                target = args[1];
            }
            for (int index = gesture == null ? 2 : args.length; index < args.length; index++) {
                if (args[index].equals("--package") && index + 1 < args.length) packageFilter = args[++index];
                else throw new IllegalArgumentException("Unexpected argument: " + args[index]);
            }
            handler.start();
            Class<?> connectionInterface = Class.forName("android.app.IUiAutomationConnection");
            Object connection = Class.forName("android.app.UiAutomationConnection").getDeclaredConstructor().newInstance();
            Constructor<UiAutomation> constructor = UiAutomation.class.getDeclaredConstructor(Looper.class, connectionInterface);
            constructor.setAccessible(true);
            automation = constructor.newInstance(handler.getLooper(), connection);
            Method connect = UiAutomation.class.getDeclaredMethod("connect", int.class);
            connect.invoke(automation, UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES);
            AccessibilityServiceInfo serviceInfo = automation.getServiceInfo();
            serviceInfo.flags |= AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS
                | AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
                | AccessibilityServiceInfo.FLAG_INCLUDE_NOT_IMPORTANT_VIEWS;
            automation.setServiceInfo(serviceInfo);
            automation.clearCache();
            long captured = System.currentTimeMillis();
            JSONObject output = new JSONObject();
            output.put("capturedAtEpochMs", captured);
            output.put("capturedUptimeMs", SystemClock.uptimeMillis());
            output.put("source", "live_UiAutomation_no_waitForIdle");
            if (gesture != null) {
                JSONObject result = pinch(automation, gesture);
                output.put("pinch", result);
                output.put("completedAtEpochMs", System.currentTimeMillis());
                System.out.println(asciiJson(output.toString()));
                if (!result.getBoolean("injected")) throw new IllegalStateException("Pinch injection failed; see JSON failedEvents");
                return;
            }
            boolean windowTrees = action.equals("dump-windows");
            if (!windowTrees) {
            AccessibilityNodeInfo activeRoot = automation.getRootInActiveWindow();
            // New shell accessibility connections may not yet have window data.
            // Retry root availability briefly; never wait for animation/event idle.
            for (int attempt = 0; activeRoot == null && attempt < 20; attempt++) {
                SystemClock.sleep(50);
                automation.clearCache();
                activeRoot = automation.getRootInActiveWindow();
            }
            if (activeRoot == null) throw new IllegalStateException("No live active accessibility root; no previous snapshot is returned");
            // The active tree is authoritative and also used for exact-match tapping.
            try { output.put("root", walk(activeRoot, "active", 0)); }
            finally { activeRoot.recycle(); }
            }
            JSONArray windows = new JSONArray();
            List<AccessibilityWindowInfo> windowSnapshot = automation.getWindows();
            if (windowTrees) {
                // New connections need time to receive interactive-window data,
                // especially for non-focusable overlays. Retry fresh window lists
                // rather than returning an empty tree or reusing any older dump.
                long deadline = SystemClock.uptimeMillis() + 1000;
                int retries = 0;
                while (!hasWindowRoot(windowSnapshot) && SystemClock.uptimeMillis() < deadline) {
                    SystemClock.sleep(Math.min(50, Math.max(1, deadline - SystemClock.uptimeMillis())));
                    automation.clearCache();
                    windowSnapshot = automation.getWindows();
                    retries++;
                }
                output.put("windowRootRetries", retries);
            }
            for (AccessibilityWindowInfo window : windowSnapshot) {
                JSONObject info = new JSONObject();
                info.put("id", window.getId());
                info.put("type", window.getType());
                info.put("title", string(window.getTitle()));
                info.put("active", window.isActive());
                info.put("focused", window.isFocused());
                if (windowTrees) {
                    AccessibilityNodeInfo windowRoot = window.getRoot();
                    try {
                        info.put("root", windowRoot == null ? JSONObject.NULL : walk(windowRoot, "window/" + window.getId(), 0));
                    } finally { if (windowRoot != null) windowRoot.recycle(); }
                }
                // Root duplicates would create ambiguous tap matches, so windows are metadata only.
                windows.put(info);
            }
            output.put("windows", windows);
            if (windowTrees && visited == 0) throw new IllegalStateException("No live window accessibility roots; no previous snapshot is returned");
            output.put("nodeCount", visited);
            output.put("truncated", visited >= MAX_NODES);
            output.put("matches", matchPayloads);
            if (action.startsWith("tap-")) output.put("tap", tap(automation));
            output.put("completedAtEpochMs", System.currentTimeMillis());
            System.out.println(asciiJson(output.toString()));
        } catch (Throwable error) {
            error.printStackTrace(System.err);
            System.exit(1);
        } finally {
            for (AccessibilityNodeInfo match : matches) match.recycle();
            if (automation != null) {
                try { UiAutomation.class.getDeclaredMethod("disconnect").invoke(automation); }
                catch (Throwable ignored) {}
            }
            handler.quitSafely();
        }
    }
}
