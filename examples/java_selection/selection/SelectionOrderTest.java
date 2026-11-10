package selection;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

public final class SelectionOrderTest {
    private static int assertions;

    private static void equal(List<String> expected, List<String> actual) {
        assertions++;
        if (!expected.equals(actual)) throw new AssertionError("selection order differs");
    }

    public static void main(String[] args) {
        equal(List.of("z.py", "a.py"), SelectionOrder.unique(List.of("z.py", "a.py", "z.py")));
        equal(List.of(), SelectionOrder.unique(List.of()));
        equal(List.of("one"), SelectionOrder.unique(List.of("one", "one")));
        equal(List.of("b", "A", "a"), SelectionOrder.unique(List.of("b", "A", "b", "a")));
        List<String> original = new ArrayList<>(List.of("c", "b", "c"));
        SelectionOrder.unique(original);
        equal(List.of("c", "b", "c"), original);
        equal(Arrays.asList("x", null, "y"), SelectionOrder.unique(Arrays.asList("x", null, "x", "y")));
        System.out.println(assertions + " protected assertions passed");
    }
}
