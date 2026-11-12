import java.util.jar.*; import java.io.*; import org.jboss.jandex.Indexer;
public class Scan { public static void main(String[] a) throws Exception {
  try (JarFile jf = new JarFile(a[0])) { var en = jf.entries(); int n=0, bad=0;
    while (en.hasMoreElements()) { JarEntry e = en.nextElement(); if (!e.getName().endsWith(".class")) continue; n++;
      try (InputStream in = jf.getInputStream(e)) { new Indexer().index(in); } catch (Throwable t) { bad++; System.out.println("BAD " + e.getName() + " " + t); } }
    System.out.println("classes=" + n + " bad=" + bad); } } }
