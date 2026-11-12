import net.bytebuddy.jar.asm.*;
import java.nio.file.*;

/**
 * Removes type-use annotation attributes (RuntimeVisibleTypeAnnotations and
 * RuntimeInvisibleTypeAnnotations) from the given class files, in place.
 *
 * Why: the Jandex version bundled with the HAPI FHIR 5.7.0 CLI crashes with
 * ArrayIndexOutOfBoundsException while indexing 10 Guava classes that carry
 * Checker Framework type-use annotations, so `run-server` cannot start.
 * Type-use annotations are metadata only; method bytecode is copied unchanged.
 * Uses the ASM copy that ships inside the HAPI CLI jar (net.bytebuddy.jar.asm).
 */
public class Strip {
    public static void main(String[] args) throws Exception {
        for (String p : args) {
            ClassReader cr = new ClassReader(Files.readAllBytes(Path.of(p)));
            ClassWriter cw = new ClassWriter(0);
            cr.accept(new ClassVisitor(Opcodes.ASM9, cw) {
                @Override public AnnotationVisitor visitTypeAnnotation(int r, TypePath t, String d, boolean v) { return null; }
                @Override public FieldVisitor visitField(int ac, String n, String d, String s, Object val) {
                    return new FieldVisitor(Opcodes.ASM9, super.visitField(ac, n, d, s, val)) {
                        @Override public AnnotationVisitor visitTypeAnnotation(int r, TypePath t, String d2, boolean v) { return null; }
                    };
                }
                @Override public MethodVisitor visitMethod(int ac, String n, String d, String s, String[] ex) {
                    return new MethodVisitor(Opcodes.ASM9, super.visitMethod(ac, n, d, s, ex)) {
                        @Override public AnnotationVisitor visitTypeAnnotation(int r, TypePath t, String d2, boolean v) { return null; }
                        @Override public AnnotationVisitor visitInsnAnnotation(int r, TypePath t, String d2, boolean v) { return null; }
                        @Override public AnnotationVisitor visitTryCatchAnnotation(int r, TypePath t, String d2, boolean v) { return null; }
                        @Override public AnnotationVisitor visitLocalVariableAnnotation(int r, TypePath t, Label[] s2, Label[] e2, int[] i, String d2, boolean v) { return null; }
                    };
                }
            }, 0);
            Files.write(Path.of(p), cw.toByteArray());
            System.out.println("stripped type annotations: " + p);
        }
    }
}
