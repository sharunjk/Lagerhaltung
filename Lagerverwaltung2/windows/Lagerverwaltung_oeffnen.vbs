' Oeffnet die Lagerverwaltung als eigenes Fenster (ohne Browser-Leisten).
' Laeuft die Lagerverwaltung noch nicht, wird sie vorher unsichtbar im Hintergrund gestartet.
Option Explicit
Dim sh, fso, ordner, port, url, cfg, zeile, i, abschnitt
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
ordner = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))

' Port aus config.toml lesen - nur Abschnitt [server] (unter [drucker] steht ebenfalls "port = 9100")
port = "8080"
abschnitt = ""
If fso.FileExists(ordner & "\config.toml") Then
  Set cfg = fso.OpenTextFile(ordner & "\config.toml", 1)
  Do Until cfg.AtEndOfStream
    zeile = Trim(cfg.ReadLine)
    If Left(zeile, 3) = Chr(239) & Chr(187) & Chr(191) Then zeile = Mid(zeile, 4)
    If Left(zeile, 1) = "[" Then
      abschnitt = LCase(Trim(Replace(Replace(Split(zeile, "#")(0), "[", ""), "]", "")))
    ElseIf abschnitt = "server" And InStr(zeile, "=") > 0 Then
      If LCase(Trim(Split(zeile, "=")(0))) = "port" Then
        port = Trim(Split(Split(zeile, "=")(1), "#")(0))
        If Not IsNumeric(port) Then port = "8080"
        Exit Do
      End If
    End If
  Loop
  cfg.Close
End If
url = "http://localhost:" & port & "/"

Function Laeuft()
  Dim h
  On Error Resume Next
  Set h = CreateObject("MSXML2.ServerXMLHTTP.6.0")
  h.setTimeouts 800, 800, 800, 800
  h.Open "GET", url & "m/ping", False
  h.Send
  Laeuft = (Err.Number = 0 And h.Status = 200)
  Err.Clear
  On Error GoTo 0
End Function

If Not Laeuft() Then
  If Not fso.FileExists(ordner & "\python\pythonw.exe") Then
    MsgBox "Die Lagerverwaltung ist noch nicht eingerichtet. Bitte zuerst windows\1_EINRICHTEN.bat ausfuehren.", 48, "Lagerverwaltung"
    WScript.Quit 1
  End If
  sh.CurrentDirectory = ordner
  sh.Run """" & ordner & "\python\pythonw.exe"" -m app.main", 0, False
  For i = 1 To 40
    WScript.Sleep 500
    If Laeuft() Then Exit For
  Next
  If Not Laeuft() Then
    MsgBox "Die Lagerverwaltung startet nicht. Details: " & ordner & "\logs\lagerverwaltung.log", 16, "Lagerverwaltung"
    WScript.Quit 1
  End If
End If

' Als App-Fenster oeffnen: Edge, sonst Chrome, sonst Standardbrowser
On Error Resume Next
sh.Run "msedge.exe --app=" & url & " --window-size=1400,900", 1, False
If Err.Number <> 0 Then
  Err.Clear
  sh.Run "chrome.exe --app=" & url & " --window-size=1400,900", 1, False
  If Err.Number <> 0 Then
    Err.Clear
    sh.Run url, 1, False
  End If
End If
