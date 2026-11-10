package selection;

import java.util.ArrayList;
import java.util.List;
import java.util.TreeSet;
import java.util.LinkedHashSet;

/** Invented explicit-file selection fixture; initially sorts the caller's order. */
public final class SelectionOrder {
    private SelectionOrder() { }

    public static List<String> unique(List<String> values) {
        return new ArrayList<>(new TreeSet<>(values));
    }
}
