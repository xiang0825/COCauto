import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

class AvailableRelease {
  const AvailableRelease({
    required this.version,
    required this.page,
    required this.notes,
  });

  final String version;
  final Uri page;
  final String notes;
}

abstract interface class ReleaseChecker {
  Future<AvailableRelease?> check(String currentVersion);
}

/// Checks the public release feed only when the app enters the foreground.
class GitHubReleaseChecker implements ReleaseChecker {
  static final Uri _apiUri = Uri.parse(
    'https://api.github.com/repos/xiang0825/COCauto/releases?per_page=20',
  );

  GitHubReleaseChecker({HttpClient Function()? clientFactory})
    : _clientFactory = clientFactory ?? HttpClient.new;

  final HttpClient Function() _clientFactory;

  @override
  Future<AvailableRelease?> check(String currentVersion) async {
    final client = _clientFactory()
      ..connectionTimeout = const Duration(seconds: 3);
    try {
      final request = await client
          .getUrl(_apiUri)
          .timeout(const Duration(seconds: 5));
      request
        ..followRedirects = false
        ..maxRedirects = 0
        ..headers.set(HttpHeaders.acceptHeader, 'application/vnd.github+json')
        ..headers.set(HttpHeaders.userAgentHeader, 'CoCauto-Android')
        ..headers.set(HttpHeaders.cacheControlHeader, 'no-cache');
      final response = await request.close().timeout(
        const Duration(seconds: 5),
      );
      if (response.statusCode != HttpStatus.ok || response.isRedirect) {
        await response.drain<void>();
        return null;
      }
      if (response.contentLength > 512 * 1024) {
        await response.drain<void>();
        return null;
      }
      final bytes = BytesBuilder(copy: false);
      await for (final chunk in response.timeout(const Duration(seconds: 5))) {
        if (bytes.length + chunk.length > 512 * 1024) return null;
        bytes.add(chunk);
      }
      final decoded = jsonDecode(utf8.decode(bytes.takeBytes()));
      return parseLatestRelease(decoded, currentVersion: currentVersion);
    } catch (_) {
      // Release information is optional; offline use remains quiet.
      return null;
    } finally {
      client.close(force: true);
    }
  }
}

int compareReleaseVersions(String latest, String current) {
  final latestVersion = _ReleaseVersion.tryParse(latest);
  final currentVersion = _ReleaseVersion.tryParse(current);
  if (latestVersion == null || currentVersion == null) return 0;

  final coreLength = latestVersion.core.length > currentVersion.core.length
      ? latestVersion.core.length
      : currentVersion.core.length;
  for (var index = 0; index < coreLength; index++) {
    final left = index < latestVersion.core.length
        ? latestVersion.core[index]
        : 0;
    final right = index < currentVersion.core.length
        ? currentVersion.core[index]
        : 0;
    if (left != right) return left.compareTo(right);
  }

  final latestPrerelease = latestVersion.prerelease;
  final currentPrerelease = currentVersion.prerelease;
  if (latestPrerelease == null || currentPrerelease == null) {
    if (latestPrerelease == currentPrerelease) return 0;
    return latestPrerelease == null ? 1 : -1;
  }

  final prereleaseLength = latestPrerelease.length > currentPrerelease.length
      ? latestPrerelease.length
      : currentPrerelease.length;
  for (var index = 0; index < prereleaseLength; index++) {
    if (index >= latestPrerelease.length) return -1;
    if (index >= currentPrerelease.length) return 1;
    final comparison = latestPrerelease[index].compareTo(
      currentPrerelease[index],
    );
    if (comparison != 0) return comparison;
  }
  return 0;
}

class _ReleaseVersion {
  const _ReleaseVersion(this.core, this.prerelease);

  final List<int> core;
  final List<_VersionIdentifier>? prerelease;

  static _ReleaseVersion? tryParse(String input) {
    var version = input.trim().replaceFirst(RegExp(r'^[vV]'), '');
    if (version.isEmpty) return null;

    final buildIndex = version.indexOf('+');
    if (buildIndex >= 0) {
      final metadata = version.substring(buildIndex + 1);
      if (metadata.isEmpty ||
          !RegExp(r'^[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*$').hasMatch(metadata)) {
        return null;
      }
      version = version.substring(0, buildIndex);
    }
    if (version.contains('+')) return null;

    final prereleaseIndex = version.indexOf('-');
    final coreText = prereleaseIndex < 0
        ? version
        : version.substring(0, prereleaseIndex);
    final prereleaseText = prereleaseIndex < 0
        ? null
        : version.substring(prereleaseIndex + 1);
    if (!RegExp(r'^\d+(?:\.\d+)*$').hasMatch(coreText)) return null;

    final core = <int>[];
    for (final component in coreText.split('.')) {
      final parsed = int.tryParse(component);
      if (parsed == null) return null;
      core.add(parsed);
    }

    if (prereleaseText == null) return _ReleaseVersion(core, null);
    final prerelease = _parsePrerelease(prereleaseText);
    if (prerelease == null) return null;
    return _ReleaseVersion(core, prerelease);
  }

  static List<_VersionIdentifier>? _parsePrerelease(String value) {
    if (value.isEmpty) return null;
    final tokens = <_VersionIdentifier>[];
    final tokenPattern = RegExp(r'\d+|[A-Za-z-]+');
    for (final identifier in value.split('.')) {
      if (identifier.isEmpty ||
          !RegExp(r'^[0-9A-Za-z-]+$').hasMatch(identifier)) {
        return null;
      }
      var offset = 0;
      for (final match in tokenPattern.allMatches(identifier)) {
        if (match.start != offset) return null;
        offset = match.end;
        final token = match.group(0)!;
        final numeric = int.tryParse(token);
        tokens.add(
          numeric == null
              ? _VersionIdentifier.text(token.toLowerCase())
              : _VersionIdentifier.number(numeric),
        );
      }
      if (offset != identifier.length) return null;
    }
    return tokens;
  }
}

class _VersionIdentifier {
  const _VersionIdentifier.number(this.numeric) : text = '';
  const _VersionIdentifier.text(this.text) : numeric = null;

  final int? numeric;
  final String text;

  int compareTo(_VersionIdentifier other) {
    if (numeric != null && other.numeric != null) {
      return numeric!.compareTo(other.numeric!);
    }
    if (numeric != null) return -1;
    if (other.numeric != null) return 1;
    return text.compareTo(other.text);
  }
}

AvailableRelease? parseLatestRelease(
  Object? value, {
  required String currentVersion,
}) {
  final entries = switch (value) {
    List<dynamic> items => items.whereType<Map<String, dynamic>>(),
    Map<String, dynamic> item => [item],
    _ => const <Map<String, dynamic>>[],
  };
  AvailableRelease? best;
  for (final entry in entries) {
    if (entry['draft'] != false) continue;
    final version = entry['tag_name'];
    if (version is! String ||
        version.isEmpty ||
        version.length > 64 ||
        compareReleaseVersions(version, currentVersion) <= 0 ||
        (best != null && compareReleaseVersions(version, best.version) <= 0)) {
      continue;
    }
    final pageValue = entry['html_url'];
    if (pageValue is! String) throw const FormatException('GitHub 发布页地址无效');
    final page = Uri.tryParse(pageValue);
    if (page == null ||
        page.scheme != 'https' ||
        page.host.toLowerCase() != 'github.com' ||
        page.userInfo.isNotEmpty ||
        page.hasQuery ||
        page.hasFragment ||
        !page.path.startsWith('/xiang0825/COCauto/releases/')) {
      throw const FormatException('GitHub 发布页不属于 CoCauto 项目');
    }
    final notes = entry['body'];
    best = AvailableRelease(
      version: version,
      page: page,
      notes: notes is String
          ? notes.substring(0, notes.length.clamp(0, 16000))
          : '',
    );
  }
  return best;
}
