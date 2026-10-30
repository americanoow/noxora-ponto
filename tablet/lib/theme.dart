
import 'package:flutter/material.dart';

/// Tokens da identidade Noxora Ponto (mesmos valores do painel web, em `frontend/src/ui/theme.css`).
/// Regra do "ponto": preenchido = estado real; vazado = pendente; cor de borda = decorativo.
class NoxoraColors {
  static const bg = Color(0xFFF5F2EC);
  static const bgAlt = Color(0xFFFAF8F4);
  static const surface = Color(0xFFFFFFFF);
  static const line = Color(0xFFE5E0D8);
  static const lineStrong = Color(0xFFD3CCC0);
  static const ink = Color(0xFF282D2B);
  static const ink2 = Color(0xFF626862);
  static const accent = Color(0xFF456B60);
  static const accentStrong = Color(0xFF355449);
  static const accentSoft = Color(0xFFE2EBE7);
  static const warn = Color(0xFF8A5A12);
  static const warnSoft = Color(0xFFF5E9D0);
  static const danger = Color(0xFF9C3F34);
  static const dangerSoft = Color(0xFFF4E0DB);
}

/// Algarismos de largura fixa: o relógio e os totais não "dançam" a cada segundo.
const tabularFigures = [FontFeature.tabularFigures()];

ThemeData noxoraTheme() {
  final scheme = ColorScheme.fromSeed(
    seedColor: NoxoraColors.accent,
    brightness: Brightness.light,
  ).copyWith(
    primary: NoxoraColors.accent,
    onPrimary: Colors.white,
    surface: NoxoraColors.surface,
    onSurface: NoxoraColors.ink,
    error: NoxoraColors.danger,
    outline: NoxoraColors.lineStrong,
  );
  final base = ThemeData(useMaterial3: true, colorScheme: scheme);
  final radius = BorderRadius.circular(14);
  return base.copyWith(
    scaffoldBackgroundColor: NoxoraColors.bg,
    textTheme: base.textTheme.apply(
      bodyColor: NoxoraColors.ink,
      displayColor: NoxoraColors.ink,
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size(0, 64),
        padding: const EdgeInsets.symmetric(horizontal: 28),
        shape: RoundedRectangleBorder(borderRadius: radius),
        textStyle: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: const Size(0, 56),
        shape: RoundedRectangleBorder(borderRadius: radius),
        side: const BorderSide(color: NoxoraColors.lineStrong),
        textStyle: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        minimumSize: const Size(0, 48),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: NoxoraColors.surface,
      contentPadding: const EdgeInsets.symmetric(horizontal: 18, vertical: 18),
      border: OutlineInputBorder(
        borderRadius: radius,
        borderSide: const BorderSide(color: NoxoraColors.lineStrong),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: radius,
        borderSide: const BorderSide(color: NoxoraColors.lineStrong),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: radius,
        borderSide: const BorderSide(color: NoxoraColors.accent, width: 2),
      ),
    ),
    chipTheme: base.chipTheme.copyWith(
      backgroundColor: NoxoraColors.surface,
      selectedColor: NoxoraColors.accent,
      side: const BorderSide(color: NoxoraColors.lineStrong),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(999)),
      labelStyle: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
    ),
  );
}

/// O "ponto": círculo preenchido (estado real) ou vazado (pendente).
class StatusDot extends StatelessWidget {
  const StatusDot({super.key, required this.color, this.hollow = false, this.size = 12});
  final Color color;
  final bool hollow;
  final double size;

  @override
  Widget build(BuildContext context) => Container(
        width: size,
        height: size,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: hollow ? Colors.transparent : color,
          border: hollow ? Border.all(color: color, width: 2.5) : null,
        ),
      );
}
